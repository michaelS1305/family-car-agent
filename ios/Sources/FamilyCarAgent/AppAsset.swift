import SwiftUI
import UIKit

/// Loads PNG resources from the validated FCA AppAssets bundle.
enum AppAsset {
    static func load(_ relativePath: String) -> UIImage? {
        guard !relativePath.isEmpty,
              !relativePath.hasPrefix("/"),
              !relativePath.contains(".."),
              relativePath.hasSuffix(".png"),
              let url = Bundle.module.url(
                  forResource: relativePath,
                  withExtension: nil,
                  subdirectory: "AppAssets"
              ) else {
            return nil
        }

        return UIImage(contentsOfFile: url.path)
    }
}

/// Displays an FCA asset without changing its original aspect ratio.
struct AppAssetImage: View {
    let path: String
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        Group {
            if let image = AppAsset.load(path == FCABranding.lightWordmark
                                        ? FCABranding.wordmark(dark: colorScheme == .dark) : path) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
            } else {
                EmptyView()
            }
        }
    }
}

/// Keep the original Light compositing at each existing call site. The approved
/// white Dark wordmark must not be multiplied into a dark background.
struct FCAWordmarkBlend: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme
    func body(content: Content) -> some View {
        content.blendMode(colorScheme == .dark ? .normal : .multiply)
    }
}
