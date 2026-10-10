// Draws the Jarvis app icon (1024 x 1024 PNG): a glowing blue ring with a "J" on deep navy,
// matching the dashboard's voice orb. Usage: swift make_icon.swift <output.png>

import AppKit

let size = 1024.0
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.png"
let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()
let ctx = NSGraphicsContext.current!.cgContext

// rounded-square background (macOS icon grid: 824 px body inside 1024)
let body = NSRect(x: 100, y: 100, width: 824, height: 824)
let bg = NSBezierPath(roundedRect: body, xRadius: 185, yRadius: 185)
NSGradient(colors: [NSColor(red: 0.07, green: 0.12, blue: 0.24, alpha: 1),
                    NSColor(red: 0.03, green: 0.05, blue: 0.11, alpha: 1)])!.draw(in: bg, angle: -90)

// glow + ring
let center = CGPoint(x: size / 2, y: size / 2)
for (radius, alpha) in [(330.0, 0.10), (300.0, 0.16), (276.0, 0.24)] {
    ctx.setFillColor(NSColor(red: 0.23, green: 0.51, blue: 0.96, alpha: alpha).cgColor)
    ctx.fillEllipse(in: CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2))
}
ctx.setFillColor(NSColor(red: 0.05, green: 0.09, blue: 0.19, alpha: 1).cgColor)
ctx.fillEllipse(in: CGRect(x: center.x - 250, y: center.y - 250, width: 500, height: 500))
ctx.setStrokeColor(NSColor(red: 0.30, green: 0.58, blue: 1.0, alpha: 1).cgColor)
ctx.setLineWidth(26)
ctx.strokeEllipse(in: CGRect(x: center.x - 250, y: center.y - 250, width: 500, height: 500))

// "J"
let style = NSMutableParagraphStyle()
style.alignment = .center
let font = NSFont.systemFont(ofSize: 300, weight: .heavy)
let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: NSColor(red: 0.92, green: 0.95, blue: 1, alpha: 1),
                                            .paragraphStyle: style]
let text = NSAttributedString(string: "J", attributes: attrs)
let h = text.size().height
text.draw(in: NSRect(x: 0, y: center.y - h / 2 - 10, width: size, height: h))
image.unlockFocus()

let rep = NSBitmapImageRep(data: image.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
