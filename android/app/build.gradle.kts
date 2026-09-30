import java.util.Properties
plugins { id("com.android.application") }
val config = Properties().apply {
    rootProject.file("fca.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
}
fun setting(name: String) = "\"" + config.getProperty(name, "").replace("\\", "\\\\").replace("\"", "\\\"") + "\""
android {
    namespace = "il.fca.companion"
    compileSdk = 36
    defaultConfig {
        applicationId = "il.fca.companion"
        minSdk = 35
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"
        for (key in listOf("FCA_BASE_URL", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY"))
            buildConfigField("String", key, setting(key))
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    testOptions { unitTests.isIncludeAndroidResources = true }
}
dependencies {
    implementation("androidx.work:work-runtime-ktx:2.11.2")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.16.1")
    testImplementation("androidx.work:work-testing:2.11.2")
}
