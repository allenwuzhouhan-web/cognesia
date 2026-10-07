import AppKit

// The icon is drawn from vector geometry at every resolution: no bitmap upscaling.
let output = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let iconset = output.appendingPathComponent("Cognesia.iconset", isDirectory: true)
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

enum Segment {
    case move(CGFloat, CGFloat), line(CGFloat, CGFloat)
    case curve(CGFloat, CGFloat, CGFloat, CGFloat, CGFloat, CGFloat)
}
let outline: [Segment] = [
    .move(706, 296),
    .curve(610, 214, 453, 212, 349, 307),
    .curve(235, 411, 230, 589, 339, 704),
    .curve(439, 810, 603, 823, 712, 731),
]
let branches: [Segment] = [
    .move(365, 512), .line(510, 512),
    .curve(560, 512, 577, 394, 634, 394), .line(715, 394),
    .move(510, 512), .curve(560, 512, 577, 630, 634, 630), .line(715, 630),
]
let ink = NSColor(srgbRed: 0.075, green: 0.20, blue: 0.27, alpha: 1)
let ivory = NSColor(srgbRed: 0.965, green: 0.969, blue: 0.945, alpha: 1)
let mint = NSColor(srgbRed: 0.57, green: 0.80, blue: 0.75, alpha: 1)

func cgPath(_ segments: [Segment]) -> CGPath {
    let path = CGMutablePath()
    for segment in segments {
        switch segment {
        case let .move(x, y): path.move(to: CGPoint(x: x, y: y))
        case let .line(x, y): path.addLine(to: CGPoint(x: x, y: y))
        case let .curve(a, b, c, d, x, y):
            path.addCurve(to: CGPoint(x: x, y: y), control1: CGPoint(x: a, y: b), control2: CGPoint(x: c, y: d))
        }
    }
    return path
}

func render(size: Int, name: String) throws {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: bitmap)!.cgContext
    context.scaleBy(x: CGFloat(size) / 1024, y: CGFloat(size) / 1024)
    context.translateBy(x: 0, y: 1024)
    context.scaleBy(x: 1, y: -1)
    context.setFillColor(ink.cgColor)
    context.addPath(CGPath(roundedRect: CGRect(x: 64, y: 64, width: 896, height: 896), cornerWidth: 200, cornerHeight: 200, transform: nil))
    context.fillPath()
    context.setStrokeColor(ivory.cgColor)
    context.setLineWidth(90)
    context.setLineCap(.round)
    context.setLineJoin(.round)
    context.addPath(cgPath(outline))
    context.strokePath()
    context.setStrokeColor(mint.cgColor)
    context.setLineWidth(28)
    context.addPath(cgPath(branches))
    context.strokePath()
    for (x, y, radius) in [(510.0, 512.0, 36.0), (715.0, 394.0, 31.0), (715.0, 630.0, 31.0)] {
        context.setFillColor(mint.cgColor)
        context.fillEllipse(in: CGRect(x: x - radius, y: y - radius, width: radius * 2, height: radius * 2))
    }
    try bitmap.representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent(name))
}

for size in [16, 32, 128, 256, 512] {
    try render(size: size, name: "Cognesia.iconset/icon_\(size)x\(size).png")
    try render(size: size * 2, name: "Cognesia.iconset/icon_\(size)x\(size)@2x.png")
}
try render(size: 1024, name: "Cognesia.png")
try render(size: 256, name: "Cognesia-preview.png")

func svgPath(_ segments: [Segment]) -> String {
    segments.map { segment in
        switch segment {
        case let .move(x,y): return "M\(x) \(y)"
        case let .line(x,y): return "L\(x) \(y)"
        case let .curve(a,b,c,d,x,y): return "C\(a) \(b) \(c) \(d) \(x) \(y)"
        }
    }.joined(separator: " ")
}
let svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" role="img" aria-label="Cognesia: a C connected to branching neural nodes">
  <rect x="64" y="64" width="896" height="896" rx="200" fill="#133345"/>
  <path d="\(svgPath(outline))" fill="none" stroke="#f6f7f1" stroke-width="90" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="\(svgPath(branches))" fill="none" stroke="#91ccbf" stroke-width="28" stroke-linecap="round"/>
  <g fill="#91ccbf"><circle cx="510" cy="512" r="36"/><circle cx="715" cy="394" r="31"/><circle cx="715" cy="630" r="31"/></g>
</svg>
"""
try svg.write(to: output.appendingPathComponent("Cognesia.svg"), atomically: true, encoding: .utf8)
print(output.path)
