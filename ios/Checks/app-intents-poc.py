"""Generate a disposable Xcode app wrapper; never rewrite the Swift package."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re


PROBE_ID = "com.familycaragent.intentprobe"
PROBE_NAME = "FCA Intent Probe"


def generate(ios: Path, output: Path, probe=False):
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
        entry = output / "ProbeApp.swift"
        entry.write_text('import SwiftUI\n@main struct ProbeApp: App {\n'
                         '    var body: some Scene { WindowGroup {\n'
                         '        VStack(spacing: 16) {\n'
                         '            Text("FCA Intent Probe").font(.title)\n'
                         '            Text("Run FCA Test Connection in Shortcuts.").multilineTextAlignment(.center)\n'
                         '        }.padding()\n'
                         '    } }\n}\n')
        intent = next(p for p in sources if p.name == "FCAConnectionTestIntent.swift")
        source_manifest = {str(intent.relative_to(ios)): hashlib.sha256(intent.read_bytes()).hexdigest()}
        sources = [intent, entry]
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
    build_sources = [obj("build" + r, "PBXBuildFile", fileRef=r) for r in source_refs]
    build_resources = [obj("build" + r, "PBXBuildFile", fileRef=r) for r in resource_refs]
    phases = [obj("sources", "PBXSourcesBuildPhase", buildActionMask="2147483647",
                  files=build_sources, runOnlyForDeploymentPostprocessing="0"),
              obj("frameworks", "PBXFrameworksBuildPhase", buildActionMask="2147483647",
                  files=[], runOnlyForDeploymentPostprocessing="0"),
              obj("resources", "PBXResourcesBuildPhase", buildActionMask="2147483647",
                  files=build_resources, runOnlyForDeploymentPostprocessing="0")]
    product = obj("product", "PBXFileReference", explicitFileType="wrapper.application",
                  path="FamilyCarAgent.app", sourceTree="BUILT_PRODUCTS_DIR")
    products = obj("products", "PBXGroup", name="Products", children=[product], sourceTree="<group>")
    group = obj("rootgroup", "PBXGroup", children=source_refs + resource_refs + [products], sourceTree="<group>")

    def configs(key, settings):
        debug = obj(key + "debug", "XCBuildConfiguration", name="Debug", buildSettings=settings)
        return obj(key + "configs", "XCConfigurationList", buildConfigurations=[debug],
                   defaultConfigurationIsVisible="0", defaultConfigurationName="Debug")

    target_config = configs("target", {
        "PRODUCT_NAME": "FamilyCarAgent", "PRODUCT_MODULE_NAME": "FamilyCarAgent",
        "PRODUCT_BUNDLE_IDENTIFIER": config["bundleID"],
        "INFOPLIST_FILE": str(info_path), "GENERATE_INFOPLIST_FILE": "YES",
        "CODE_SIGN_ENTITLEMENTS": str(entitlements_path),
        "CODE_SIGNING_ALLOWED": "NO", "CODE_SIGNING_REQUIRED": "NO",
        "SWIFT_VERSION": "6.0", "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "DEBUG",
        "SWIFT_OPTIMIZATION_LEVEL": "-Onone", "IPHONEOS_DEPLOYMENT_TARGET": "17.0",
        "SDKROOT": "iphoneos", "SUPPORTED_PLATFORMS": "iphoneos",
        "TARGETED_DEVICE_FAMILY": "1", "CURRENT_PROJECT_VERSION": "1",
        "MARKETING_VERSION": "1.0", "ENABLE_APP_INTENTS_METADATA_EXTRACTION": "YES",
    })
    target = obj("target", "PBXNativeTarget", name="FamilyCarAgent", productName="FamilyCarAgent",
                 productType="com.apple.product-type.application", productReference=product,
                 buildConfigurationList=target_config, buildPhases=phases, buildRules=[], dependencies=[])
    project = obj("project", "PBXProject", buildConfigurationList=configs("project", {}),
                  compatibilityVersion="Xcode 14.0", developmentRegion="en", knownRegions=["en", "Base"],
                  mainGroup=group, productRefGroup=products, projectDirPath="", projectRoot="", targets=[target])
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
    with (app / "Info.plist").open("rb") as f:
        info = plistlib.load(f)
    result = {"bundle_id_matches_expected": info.get("CFBundleIdentifier") == (PROBE_ID if probe else "com.familycaragent.app.dev"),
              "environment_matches_expected": info.get("FCAEnvironment") == ("intentprobe" if probe else "development"),
              "display_name_matches": not probe or info.get("CFBundleDisplayName") == PROBE_NAME,
              "metadata_files": [str(p.relative_to(app)) for p in nonempty],
              "intent_metadata_matches": matches, "device_discovery_verified": False}
    report.write_text(json.dumps(result, indent=2) + "\n")
    if not (result["bundle_id_matches_expected"] and result["environment_matches_expected"] and result["display_name_matches"] and matches):
        raise ValueError("App Intents metadata/Dev identity check failed; inspect metadata-report.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["generate", "verify"])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    (generate if args.mode == "generate" else verify)(args.source, args.output, args.probe)
