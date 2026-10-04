import java.util.Properties
import java.util.Base64
plugins { id("com.android.application") }
data class FcaEnvironment(val id: String, val label: String, val backend: String, val project: String) {
    val supabase get() = "https://$project.supabase.co"
    val callback get() = "$id://auth/callback"
}
val environments = mapOf(
    "dev" to FcaEnvironment("il.fca.companion.dev", "FCA Companion Dev",
        "https://family-car-agent-dev.onrender.com", "jouhqvbxhsvkluwkqmdg"),
    "prod" to FcaEnvironment("il.fca.companion", "FCA Companion",
        "https://family-car-agent.onrender.com", "xrgijytfigcuxmdktvmd"),
)
fun validateConfiguration(env: FcaEnvironment, config: Properties) {
    mapOf("FCA_BASE_URL" to env.backend, "SUPABASE_URL" to env.supabase,
        "OAUTH_CALLBACK_URI" to env.callback).forEach { (name, expected) ->
        require(config.getProperty(name) == expected) { "$name is missing or does not match the selected FCA environment" }
    }
    val key = config.getProperty("SUPABASE_PUBLISHABLE_KEY", "")
    // Do not include the supplied value (or parsing exceptions) in build errors.
    val publicKey = key.matches(Regex("sb_publishable_[A-Za-z0-9_-]+"))
    val legacyAnon = runCatching {
        require(key.matches(Regex("[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+")))
        val parts = key.split('.')
        require(parts.size == 3)
        val claims = groovy.json.JsonSlurper().parseText(
            String(Base64.getUrlDecoder().decode(parts[1]), Charsets.UTF_8)) as Map<*, *>
        claims["role"] == "anon" && claims["ref"] == env.project
    }.getOrDefault(false)
    require(publicKey || legacyAnon) { "SUPABASE_PUBLISHABLE_KEY must be a public publishable key or this project's legacy anon key" }
}
fun quoted(value: String) = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"")
    .replace("\n", "\\n").replace("\r", "\\r") + "\""
val configurations = environments.mapValues { (flavor, _) ->
    Properties().apply {
        rootProject.file("fca.$flavor.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
    }
}
android {
    namespace = "il.fca.companion"
    compileSdk = 36
    defaultConfig {
        applicationId = "il.fca.companion"
        minSdk = 35
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"
    }
    flavorDimensions += "environment"
    productFlavors {
        environments.forEach { (flavor, env) ->
            create(flavor) {
                dimension = "environment"
                applicationId = env.id
                resValue("string", "app_name", env.label)
                manifestPlaceholders["oauthScheme"] = env.id
                buildConfigField("String", "FCA_BASE_URL", quoted(env.backend))
                buildConfigField("String", "SUPABASE_URL", quoted(env.supabase))
                buildConfigField("String", "OAUTH_CALLBACK_URI", quoted(env.callback))
                buildConfigField("String", "SUPABASE_PUBLISHABLE_KEY",
                    quoted(configurations.getValue(flavor).getProperty("SUPABASE_PUBLISHABLE_KEY", "")))
            }
        }
    }
    buildFeatures { buildConfig = true; resValues = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    testOptions { unitTests.isIncludeAndroidResources = true }
}
androidComponents.onVariants { variant ->
    val flavor = variant.productFlavors.single { it.first == "environment" }.second
    val suffix = variant.name.replaceFirstChar { it.uppercaseChar() }
    val validation = tasks.register("validate${suffix}Environment") {
        doLast {
            try { validateConfiguration(environments.getValue(flavor), configurations.getValue(flavor)) }
            catch (e: IllegalArgumentException) {
                throw GradleException("Invalid fca.$flavor.properties: ${e.message}")
            }
        }
    }
    tasks.configureEach {
        if (name == "pre${suffix}Build" || name == "generate${suffix}BuildConfig") dependsOn(validation)
    }
}
// Offline tests exercise the same guard used by every variant, without real keys.
tasks.register("testEnvironmentConfiguration") {
    doLast {
        var checks = 0
        environments.forEach { (_, env) ->
            fun valid() = Properties().apply {
                setProperty("FCA_BASE_URL", env.backend)
                setProperty("SUPABASE_URL", env.supabase)
                setProperty("OAUTH_CALLBACK_URI", env.callback)
                setProperty("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_offline_test_fixture")
            }
            validateConfiguration(env, valid()); checks++
            val other = environments.values.single { it != env }
            mapOf("FCA_BASE_URL" to other.backend, "SUPABASE_URL" to other.supabase,
                "OAUTH_CALLBACK_URI" to other.callback, "SUPABASE_PUBLISHABLE_KEY" to "sb_secret_rejected").forEach { (key, value) ->
                check(runCatching { validateConfiguration(env, valid().apply { setProperty(key, value) }) }.isFailure)
                checks++
            }
            valid().stringPropertyNames().forEach { key ->
                check(runCatching { validateConfiguration(env, valid().apply { remove(key) }) }.isFailure)
                checks++
            }
            fun legacy(project: String, role: String) = "fixture." + Base64.getUrlEncoder().withoutPadding()
                .encodeToString("{\"ref\":\"$project\",\"role\":\"$role\"}".toByteArray()) + ".fixture"
            validateConfiguration(env, valid().apply {
                setProperty("SUPABASE_PUBLISHABLE_KEY", legacy(env.project, "anon"))
            }); checks++
            listOf(legacy(other.project, "anon"), legacy(env.project, "service_role"), "malformed").forEach { key ->
                check(runCatching { validateConfiguration(env, valid().apply {
                    setProperty("SUPABASE_PUBLISHABLE_KEY", key)
                }) }.isFailure)
                checks++
            }
        }
        logger.lifecycle("FCA environment guard checks passed: $checks")
    }
}
dependencies {
    implementation("androidx.work:work-runtime-ktx:2.11.2")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.16.1")
    testImplementation("androidx.work:work-testing:2.11.2")
}
