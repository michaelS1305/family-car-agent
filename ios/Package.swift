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
    dependencies: [
        .package(url: "https://github.com/firebase/firebase-ios-sdk.git", exact: "12.19.3"),
    ],
    targets: [
        .target(
            name: "FamilyCarAgent",
            dependencies: [.product(name: "FirebaseMessaging", package: "firebase-ios-sdk", condition: .when(platforms: [.iOS]))],
            resources: [
                .copy("Resources/EntryAssets"),
                .copy("Resources/AppAssets")
            ]
        ),
    ]
)
