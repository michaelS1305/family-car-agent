import AuthenticationServices
import UIKit

@MainActor final class NativeProviders: NSObject, NativeAuthProvider, ASWebAuthenticationPresentationContextProviding,
    ASAuthorizationControllerDelegate, ASAuthorizationControllerPresentationContextProviding {
    private let environment: AppEnvironment
    private let pending = AuthorizationAttempt()
    private var web: ASWebAuthenticationSession?
    private var apple: ASAuthorizationController?
    private var continuation: CheckedContinuation<ProviderResult, Error>?
    private var timeout: Task<Void, Never>?
    private var attempt: UUID?
    private var rawNonce: String?
    private var anchor: UIWindow?
    #if DEBUG
    private var appleCallbackObserved = false
    #endif

    init(environment: AppEnvironment) { self.environment = environment }
    func authorize(apple useApple: Bool) async throws -> ProviderResult {
        guard continuation == nil else { throw AuthFailure.stale }
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene })
            .filter({ $0.activationState == .foregroundActive }).flatMap(\.windows).first(where: \.isKeyWindow) else {
            throw AuthFailure.cancelled
        }
        anchor = window
        let id = UUID(); attempt = id
        let nonce = try AuthCrypto.random()
        let verifier = try AuthCrypto.random()
        rawNonce = nonce
        let authorization = PendingAuthorization(verifier: verifier, nonce: nonce, started: Date(), callbackURL: environment.proposedOAuthCallbackURL)
        let url = try authorization.authorizeURL(base: environment.supabaseURL, challenge: AuthCrypto.challenge(verifier))
        pending.begin(authorization)
        #if DEBUG
        if !useApple {
            GoogleAuthDiagnostics.event("oauth_attempt_created")
            GoogleAuthDiagnostics.event("pending_state_stored")
        }
        #endif
        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            timeout = Task { [weak self] in
                do { try await Task.sleep(for: .seconds(600)) } catch { return }
                guard let self, self.attempt == id else { return }
                #if DEBUG
                if !useApple { GoogleAuthDiagnostics.event("oauth_timeout") }
                #endif
                self.finish(.failure(AuthFailure.expired))
            }
            if useApple {
                #if DEBUG
                appleCallbackObserved = false
                AppleAuthDiagnostics.event("authorization_started_native_apple")
                #endif
                let request = ASAuthorizationAppleIDProvider().createRequest()
                request.requestedScopes = [.email, .fullName]
                request.nonce = AuthCrypto.appleNonce(nonce)
                request.state = id.uuidString
                let controller = ASAuthorizationController(authorizationRequests: [request])
                apple = controller; controller.delegate = self; controller.presentationContextProvider = self
                #if DEBUG
                AppleAuthDiagnostics.event("request_handed_to_controller_nonce_sha256_state_present")
                #endif
                controller.performRequests()
            } else {
                let session = ASWebAuthenticationSession(url: url, callbackURLScheme: environment.proposedOAuthCallbackURL.scheme) { [weak self] url, error in
                    Task { @MainActor in
                        #if DEBUG
                        GoogleAuthDiagnostics.event("callback_received_asweb_authentication_session")
                        GoogleAuthDiagnostics.flag("callback_context_current", self?.attempt == id)
                        GoogleAuthDiagnostics.flag("callback_url_present", url != nil)
                        GoogleAuthDiagnostics.flag("callback_error_present", error != nil)
                        #endif
                        guard let self, self.attempt == id else { return }
                        do {
                            guard error == nil, let url else { throw AuthFailure.cancelled }
                            let (code, verifier) = try self.pending.consume(url)
                            self.finish(.success(ProviderResult(grant: "pkce", fields: ["auth_code": code, "code_verifier": verifier])))
                        } catch {
                            #if DEBUG
                            GoogleAuthDiagnostics.event("provider_failed_before_exchange")
                            #endif
                            self.finish(.failure(error as? AuthFailure ?? .callback))
                        }
                    }
                }
                web = session; session.presentationContextProvider = self
                session.prefersEphemeralWebBrowserSession = true
                #if DEBUG
                GoogleAuthDiagnostics.event("browser_auth_start_requested")
                #endif
                if !session.start() {
                    #if DEBUG
                    GoogleAuthDiagnostics.event("browser_auth_start_rejected")
                    #endif
                    finish(.failure(AuthFailure.cancelled))
                }
            }
        }
    }
    func cancel() { finish(.failure(AuthFailure.cancelled)) }
    private func finish(_ result: Result<ProviderResult, Error>) {
        #if DEBUG
        if apple != nil && !appleCallbackObserved {
            AppleAuthDiagnostics.event("attempt_ended_without_callback_observed")
        }
        #endif
        let saved = continuation
        continuation = nil; attempt = nil; rawNonce = nil; pending.cancel()
        timeout?.cancel(); timeout = nil
        web?.cancel(); web = nil; apple = nil; anchor = nil
        saved?.resume(with: result)
    }
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor { anchor ?? UIWindow() }
    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor { anchor ?? UIWindow() }
    func authorizationController(controller: ASAuthorizationController, didCompleteWithAuthorization authorization: ASAuthorization) {
        #if DEBUG
        AppleAuthDiagnostics.event("success_callback_received")
        if controller === apple { appleCallbackObserved = true }
        AppleAuthDiagnostics.flag("callback_context_current", controller === apple && attempt != nil && rawNonce != nil)
        #endif
        guard controller === apple, let id = attempt, let nonce = rawNonce else { return }
        #if DEBUG
        let diagnosticCredential = authorization.credential as? ASAuthorizationAppleIDCredential
        AppleAuthDiagnostics.flag("credential_is_apple_id", diagnosticCredential != nil)
        if let credential = diagnosticCredential {
            AppleAuthDiagnostics.flag("identity_token_nonempty", credential.identityToken?.isEmpty == false)
            AppleAuthDiagnostics.flag("authorization_code_nonempty", credential.authorizationCode?.isEmpty == false)
            AppleAuthDiagnostics.event("state_validation_reached")
            AppleAuthDiagnostics.flag("state_validation_passed", credential.state == id.uuidString)
        }
        AppleAuthDiagnostics.event("nonce_validation_local_not_implemented_delegated_to_supabase")
        #endif
        guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
              credential.state == id.uuidString, let data = credential.identityToken,
              let token = String(data: data, encoding: .utf8), !token.isEmpty, !credential.user.isEmpty else {
            #if DEBUG
            AppleAuthDiagnostics.event("credential_validation_failed")
            #endif
            finish(.failure(AuthFailure.invalidResponse)); return
        }
        #if DEBUG
        AppleAuthDiagnostics.event("credential_validation_passed")
        #endif
        finish(.success(ProviderResult(grant: "id_token", fields: ["provider": "apple", "id_token": token, "nonce": nonce], appleUser: credential.user)))
    }
    func authorizationController(controller: ASAuthorizationController, didCompleteWithError error: Error) {
        #if DEBUG
        AppleAuthDiagnostics.event("error_callback_received")
        AppleAuthDiagnostics.error(error)
        if controller === apple { appleCallbackObserved = true }
        AppleAuthDiagnostics.flag("callback_controller_current", controller === apple)
        #endif
        guard controller === apple else { return }
        finish(.failure((error as? ASAuthorizationError)?.code == .canceled ? AuthFailure.cancelled : AuthFailure.invalidResponse))
    }
    func credentialValid(_ user: String) async throws -> Bool {
        let state = try await ASAuthorizationAppleIDProvider().credentialState(forUserID: user)
        return state == .authorized
    }
}
