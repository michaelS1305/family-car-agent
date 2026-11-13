"""Generate a disposable Xcode app wrapper; never rewrite the Swift package."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from firebase_dev_config import validate as validate_firebase, validate_bundle, SDK_VERSION


PROBE_ID = "com.familycaragent.intentprobe"
PROBE_NAME = "FCA Intent Probe"


def generate(ios: Path, output: Path, probe=False, firebase_config=None):
    ios = ios.resolve()
    output = output.resolve()
    if output == ios or ios in output.parents:
        raise ValueError("Wrapper must be outside the iOS project")
    config = dict(re.findall(r"^(bundleID|infoPath|entitlementsPath):\s*(\S+)\s*$",
                             (ios / "xtool.yml").read_text(), re.M))
    if config.get("bundleID") != "com.familycaragent.app.dev":
        raise ValueError("Expected the existing Dev bundle identifier")
    package = (ios / "Package.swift").read_text()
    resources = re.findall(r'\.copy\("([^"]+)"\)', package)
    if set(resources) != {"Resources/EntryAssets", "Resources/AppAssets"} or ".process(" in package:
        raise ValueError("Resource declarations changed; review the wrapper")
    if ".iOS(.v17)" not in package or "swift-tools-version: 6.0" not in package:
        raise ValueError("Package platform/tool version changed; review the wrapper")
    sources = sorted((ios / "Sources/FamilyCarAgent").rglob("*.swift"))
    if not probe:
        if firebase_config is None:
            raise ValueError("Firebase Dev configuration required")
        validate_firebase(firebase_config)
        if f'exact: "{SDK_VERSION}"' not in package:
            raise ValueError("Firebase SDK version mismatch")
    for required in ("FamilyCarAgentApp.swift", "FCAConnectionTestIntent.swift"):
        if not any(p.name == required for p in sources):
            raise ValueError(f"Missing required source: {required}")
    # Fail rather than replace a previous experiment's output.
    output.mkdir(parents=True, exist_ok=False)
    accessor = output / "PackageResourceAccessor.swift"
    accessor.write_text("import Foundation\nextension Bundle { static var module: Bundle { .main } }\n")
    info_path = ios / config["infoPath"]
    entitlements_path = ios / config["entitlementsPath"]
    source_manifest = {str(p.relative_to(ios)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    if probe:
        config["bundleID"] = PROBE_ID
        info_path = output / "Probe-Info.plist"
        info_path.write_bytes(plistlib.dumps({
            "CFBundleDisplayName": PROBE_NAME,
            "FCAEnvironment": "intentprobe",
            "UILaunchScreen": {},
        }))
        entitlements_path = output / "Probe.entitlements"
        entitlements_path.write_bytes(plistlib.dumps({}))
        intent = next(p for p in sources if p.name == "FCAConnectionTestIntent.swift")
        sources = [intent] + sorted((ios / "IntentProbe").glob("*.swift"))
        if len(sources) != 4:
            raise ValueError("Expected the three isolated probe sources")
        source_manifest = {str(p.relative_to(ios)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        resources = []
    objects = {}

    def obj(key, isa, **values):
        ident = hashlib.sha256(key.encode()).hexdigest()[:24].upper()
        objects[ident] = dict(isa=isa, **values)
        return ident

    def file(path, kind):
        return obj(str(path), "PBXFileReference", path=str(path), sourceTree="<absolute>",
                   lastKnownFileType=kind)

    source_refs = [file(p, "sourcecode.swift") for p in sources + [accessor]]
    resource_refs = [file(ios / "Sources/FamilyCarAgent" / p, "folder") for p in resources]
    package_refs, products, framework_builds = [], [], []
    if not probe:
        resource_refs.append(file(Path(firebase_config).resolve(), "text.plist.xml"))
        resource_refs.append(file(ios / "Config/AppIcon.xcassets", "folder.assetcatalog"))
        package_ref = obj("firebase-package", "XCRemoteSwiftPackageReference",
                          repositoryURL="https://github.com/firebase/firebase-ios-sdk.git",
                          requirement={"kind": "exactVersion", "version": SDK_VERSION})
        product_ref = obj("firebase-messaging", "XCSwiftPackageProductDependency",
                          package=package_ref, productName="FirebaseMessaging")
        package_refs.append(package_ref)
        products.append(product_ref)
        framework_builds.append(obj("firebase-link", "PBXBuildFile", productRef=product_ref))
    build_sources = [obj("build" + r, "PBXBuildFile", fileRef=r) for r in source_refs]
    build_resources = [obj("build" + r, "PBXBuildFile", fileRef=r) for r in resource_refs]
    phases = [obj("sources", "PBXSourcesBuildPhase", buildActionMask="2147483647",
                  files=build_sources, runOnlyForDeploymentPostprocessing="0"),
              obj("frameworks", "PBXFrameworksBuildPhase", buildActionMask="2147483647",
                  files=framework_builds, runOnlyForDeploymentPostprocessing="0"),
              obj("resources", "PBXResourcesBuildPhase", buildActionMask="2147483647",
                  files=build_resources, runOnlyForDeploymentPostprocessing="0")]
    product = obj("product", "PBXFileReference", explicitFileType="wrapper.application",
                  path="FamilyCarAgent.app", sourceTree="BUILT_PRODUCTS_DIR")
    products_group = obj("products", "PBXGroup", name="Products", children=[product], sourceTree="<group>")
    group = obj("rootgroup", "PBXGroup", children=source_refs + resource_refs + [products_group], sourceTree="<group>")

    def configs(key, settings):
        debug = obj(key + "debug", "XCBuildConfiguration", name="Debug", buildSettings=settings)
        return obj(key + "configs", "XCConfigurationList", buildConfigurations=[debug],
                   defaultConfigurationIsVisible="0", defaultConfigurationName="Debug")

    target_config = configs("target", {
        "PRODUCT_NAME": "FamilyCarAgent", "PRODUCT_MODULE_NAME": "FamilyCarAgent",
        "PRODUCT_BUNDLE_IDENTIFIER": config["bundleID"],
        "INFOPLIST_FILE": str(info_path), "GENERATE_INFOPLIST_FILE": "YES",
        **({"INFOPLIST_KEY_UILaunchScreen_Generation": "YES"} if not probe else {}),
        **({"ASSETCATALOG_COMPILER_APPICON_NAME": "AppIcon"} if not probe else {}),
        "CODE_SIGN_ENTITLEMENTS": str(entitlements_path),
        "CODE_SIGNING_ALLOWED": "NO", "CODE_SIGNING_REQUIRED": "NO",
        "SWIFT_VERSION": "6.0", "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "DEBUG",
        "SWIFT_OPTIMIZATION_LEVEL": "-Onone", "IPHONEOS_DEPLOYMENT_TARGET": "17.0",
        "SDKROOT": "iphoneos", "SUPPORTED_PLATFORMS": "iphoneos",
        "TARGETED_DEVICE_FAMILY": "1", "CURRENT_PROJECT_VERSION": "1",
        "MARKETING_VERSION": "1.0", "ENABLE_APP_INTENTS_METADATA_EXTRACTION": "YES",
        **({"OTHER_LDFLAGS": "$(inherited) -ObjC"} if not probe else {}),
    })
    target = obj("target", "PBXNativeTarget", name="FamilyCarAgent", productName="FamilyCarAgent",
                 productType="com.apple.product-type.application", productReference=product,
                 buildConfigurationList=target_config, buildPhases=phases, buildRules=[], dependencies=[],
                 packageProductDependencies=products)
    project = obj("project", "PBXProject", buildConfigurationList=configs("project", {}),
                  compatibilityVersion="Xcode 14.0", developmentRegion="en", knownRegions=["en", "Base"],
                  mainGroup=group, productRefGroup=products_group, projectDirPath="", projectRoot="", targets=[target],
                  packageReferences=package_refs)
    xcodeproj = output / "FCAIntentPoC.xcodeproj"
    xcodeproj.mkdir()
    with (xcodeproj / "project.pbxproj").open("wb") as f:
        plistlib.dump(dict(archiveVersion="1", classes={}, objectVersion="56", objects=objects, rootObject=project), f)
    (output / "source-manifest.json").write_text(json.dumps(source_manifest, indent=2))


def verify(app: Path, report: Path, probe=False):
    metadata = app / "Metadata.appintents"
    files = sorted(p for p in metadata.rglob("*") if p.is_file()) if metadata.is_dir() else []
    nonempty = [p for p in files if p.stat().st_size]
    matches = [str(p.relative_to(app)) for p in nonempty if b"FCAConnectionTestIntent" in p.read_bytes()]
    offline_matches = [str(p.relative_to(app)) for p in nonempty if b"FCATestOfflineUploadIntent" in p.read_bytes()]
    with (app / "Info.plist").open("rb") as f:
        info = plistlib.load(f)
    result = {"bundle_id_matches_expected": info.get("CFBundleIdentifier") == (PROBE_ID if probe else "com.familycaragent.app.dev"),
              "environment_matches_expected": info.get("FCAEnvironment") == ("intentprobe" if probe else "development"),
              "display_name_matches": not probe or info.get("CFBundleDisplayName") == PROBE_NAME,
              "metadata_files": [str(p.relative_to(app)) for p in nonempty],
              "intent_metadata_matches": matches, "offline_intent_metadata_matches": offline_matches,
              "device_discovery_verified": False}
    if not probe:
        validate_bundle(app)
        result["firebase_dev_configuration_valid"] = True
        result["launch_screen_dictionary_present"] = isinstance(info.get("UILaunchScreen"), dict)
        primary_icon = info.get("CFBundleIcons", {}).get("CFBundlePrimaryIcon", {})
        icon_files = primary_icon.get("CFBundleIconFiles", [])
        result["app_icon_present"] = (
            primary_icon.get("CFBundleIconName") == "AppIcon"
            and (app / "Assets.car").is_file()
            and (app / "Assets.car").stat().st_size > 0
            and isinstance(icon_files, list) and bool(icon_files)
            and all(isinstance(name, str) and Path(name).name == name
                    and any(p.stat().st_size > 0 for p in app.glob(name + "*.png"))
                    for name in icon_files)
        )
        actions = [b"FCATakeVehicleIntent", b"FCAReturnVehicleIntent"]
        result["vehicle_actions_present"] = all(any(action in p.read_bytes() for p in nonempty) for action in actions)
    report.write_text(json.dumps(result, indent=2) + "\n")
    if not probe and not result["launch_screen_dictionary_present"]:
        raise ValueError("Processed Dev Info.plist must contain a UILaunchScreen dictionary")
    if not probe and not result["app_icon_present"]:
        raise ValueError("Processed Dev app must contain compiled AppIcon resources and CFBundleIcons")
    if not (result["bundle_id_matches_expected"] and result["environment_matches_expected"] and result["display_name_matches"] and matches and (offline_matches if probe else result["vehicle_actions_present"])):
        raise ValueError("App Intents metadata/Dev identity check failed; inspect metadata-report.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["generate", "verify"])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--firebase-config", type=Path)
    args = parser.parse_args()
    if args.mode == "generate":
        generate(args.source, args.output, args.probe, args.firebase_config)
    else:
        verify(args.source, args.output, args.probe)
