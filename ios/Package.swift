// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "FamilyCarAgent",
    platforms: [
        .iOS(.v17),
        .macOS(.v14),
    ],
    products: [
        // An xtool project should contain exactly one library product,
        // representing the main app.
        .library(
            name: "FamilyCarAgent",
            targets: ["FamilyCarAgent"]
        ),
    ],
    targets: [
        .target(
            name: "FamilyCarAgent",
            resources: [
                .copy("Resources/EntryAssets"),
                .copy("Resources/AppAssets")
            ]
        ),
    ]
)
