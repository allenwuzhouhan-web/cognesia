import AppKit
import Foundation
import WebKit
import UniformTypeIdentifiers

enum ResearchCommand: String, CaseIterable {
    case connect, run, stop, export, audit, replicates, chemistry
    case exportPDF = "export-pdf"
    case startModel = "start-model", unloadModel = "unload-model"
    case focusPrompt = "focus-prompt", modelSetup = "model-setup"
}

@MainActor
final class ResearchWorkspaceController: NSObject, NSWindowDelegate, WKNavigationDelegate,
    WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
    let window: NSWindow
    let serviceURL: URL
    private let root: URL
    private let viewerURL: URL
    private let port: Int
    private let openWorkbench: () -> Void
    private let focused: () -> Void
    private var webView: WKWebView!
    private var status: NSView!
    private var statusText: NSTextField!
    private var retry: NSButton!
    private var task: Task<Void, Never>?
    private var ready = false
    private var enabled: [String: Bool] = [:]
    private var downloads: [ObjectIdentifier: (temporary: URL, final: URL)] = [:]
    private let session = URLSession(configuration: .ephemeral)

    init(root: URL, viewerURL: URL, port: Int, openWorkbench: @escaping () -> Void,
         focused: @escaping () -> Void) {
        self.root = root; self.viewerURL = viewerURL; self.port = port
        self.openWorkbench = openWorkbench; self.focused = focused
        serviceURL = URL(string: "http://127.0.0.1:\(port)")!
        let available = NSScreen.main?.visibleFrame.size ?? NSSize(width: 1440, height: 1000)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: min(1380, available.width - 40), height: min(900, available.height - 50)),
            styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        super.init()
        window.title = "Cognesia — Research"
        window.subtitle = "Local GPT-OSS-20B"
        window.minSize = NSSize(width: 880, height: 620)
        window.isReleasedWhenClosed = false
        window.collectionBehavior = [.fullScreenPrimary]
        window.appearance = NSAppearance(named: .darkAqua)
        window.delegate = self
        if !window.setFrameUsingName("CognesiaResearchWindow") { window.center() }
        window.setFrameAutosaveName("CognesiaResearchWindow")
        buildWebView()
    }

    private func buildWebView() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.userContentController.add(self, name: "cognesiaResearch")
        let researchBootstrap = """
        (() => {
          if (location.protocol !== 'http:' || !['127.0.0.1','localhost'].includes(location.hostname) || location.port !== '\(port)') return;
          Object.defineProperty(window, '__COGNESIA_RESEARCH_DESKTOP__', {value:true});
          window.addEventListener('cognesia-research-state', event => {
            window.webkit.messageHandlers.cognesiaResearch.postMessage(event.detail || {});
          });
        })();
        """
        configuration.userContentController.addUserScript(WKUserScript(source: researchBootstrap, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self; webView.uiDelegate = self
        webView.allowsLinkPreview = false
        webView.translatesAutoresizingMaskIntoConstraints = false
        guard let content = window.contentView else { return }
        content.addSubview(webView)
        NSLayoutConstraint.activate([webView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            webView.topAnchor.constraint(equalTo: content.topAnchor), webView.bottomAnchor.constraint(equalTo: content.bottomAnchor)])
        status = NSView(); status.wantsLayer = true
        status.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        status.translatesAutoresizingMaskIntoConstraints = false; content.addSubview(status)
        NSLayoutConstraint.activate([status.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            status.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            status.topAnchor.constraint(equalTo: content.topAnchor), status.bottomAnchor.constraint(equalTo: content.bottomAnchor)])
        let title = NSTextField(labelWithString: "Cognesia Research")
        title.font = .systemFont(ofSize: 22, weight: .semibold)
        statusText = NSTextField(wrappingLabelWithString: "Connecting to the local research service…")
        statusText.alignment = .center; statusText.isSelectable = true
        statusText.textColor = .secondaryLabelColor
        retry = NSButton(title: "Reconnect", target: self, action: #selector(reconnect))
        retry.bezelStyle = .rounded
        let logs = NSButton(title: "Show Research Logs", target: self, action: #selector(showLogs))
        logs.bezelStyle = .rounded
        let buttons = NSStackView(views: [retry, logs]); buttons.spacing = 8
        let stack = NSStackView(views: [title, statusText, buttons])
        stack.orientation = .vertical; stack.alignment = .centerX; stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false; status.addSubview(stack)
        NSLayoutConstraint.activate([stack.centerXAnchor.constraint(equalTo: status.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: status.centerYAnchor), stack.widthAnchor.constraint(equalToConstant: 510)])
    }

    var isKey: Bool { window.isKeyWindow }
    func present() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if !ready && task == nil { reconnect() }
    }
    func windowDidBecomeKey(_ notification: Notification) { focused() }
    func closeUI() { task?.cancel(); session.invalidateAndCancel() }
    func reload() { if ready { webView.reload() } else { reconnect() } }
    func zoom(_ delta: Double?) { webView.pageZoom = delta.map { min(2, max(0.65, webView.pageZoom + $0)) } ?? 1 }
    func canPerform(_ command: ResearchCommand) -> Bool {
        guard ready else { return false }
        return enabled[command.rawValue] ?? [.audit, .replicates, .chemistry, .focusPrompt, .modelSetup].contains(command)
    }
    func perform(_ command: ResearchCommand) { dispatch(command.rawValue) }

    private func dispatch(_ action: String, value: String? = nil) {
        guard ready, let url = webView.url, isResearch(url) else { NSSound.beep(); return }
        var payload: [String: String] = ["action": action]
        if let value { payload["value"] = value }
        guard let data = try? JSONSerialization.data(withJSONObject: payload), let json = String(data: data, encoding: .utf8) else { return }
        webView.evaluateJavaScript("!window.dispatchEvent(new CustomEvent('cognesia-research-command',{detail:\(json),cancelable:true}))") { _, error in
            if error != nil { NSSound.beep() }
        }
    }

    @objc private func showLogs() {
        NSWorkspace.shared.open(root.appendingPathComponent("build/runtime", isDirectory: true))
    }
    private func showStatus(_ message: String, loading: Bool) {
        ready = false; enabled.removeAll(); statusText.stringValue = message
        status.isHidden = false; retry.isHidden = loading
        window.subtitle = loading ? "Starting local research service" : "Connection unavailable"
    }

    private func available() async throws -> Bool {
        let request = URLRequest(url: serviceURL.appendingPathComponent("api/health"), cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 3)
        do {
            let (data, response) = try await session.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200,
                  let state = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  state["service"] as? String == "cognesia-research-agent",
                  state["access_required"] as? Bool == true,
                  state["viewer_url"] as? String == viewerURL.absoluteString else {
                throw NSError(domain: "Cognesia", code: 1, userInfo: [NSLocalizedDescriptionKey:
                    "Port \(port) is occupied by another service, an older unprotected console, or a console for another workbench. Existing services were left running. Check the configured ports before reconnecting."])
            }
            return true
        } catch let error as URLError where error.code == .cannotConnectToHost || error.code == .networkConnectionLost {
            return false
        }
    }

    @objc private func reconnect() {
        task?.cancel()
        showStatus("Opening the research console and the prepared local model. Existing studies and services will be reused.", loading: true)
        task = Task { [weak self] in
            guard let self else { return }
            do {
                if try await !available() { try await launch() }
                try Task.checkCancellation()
                guard try await available() else { throw NSError(domain: "Cognesia", code: 2, userInfo: [NSLocalizedDescriptionKey:"The research service has not become ready. Inspect its logs and reconnect."]) }
                webView.load(URLRequest(url: serviceURL, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 30))
            } catch is CancellationError { return }
            catch { if !Task.isCancelled { showStatus(error.localizedDescription, loading: false) } }
            task = nil
        }
    }

    private func launch() async throws {
        let process = Process(); process.executableURL = root.appendingPathComponent(".venv/bin/python")
        process.arguments = [root.appendingPathComponent("scripts/start_research_agent.py").path,
            "--no-browser", "--viewer-port", String(viewerURL.port ?? 8794), "--agent-port", String(port)]
        process.currentDirectoryURL = root; process.standardInput = FileHandle.nullDevice
        let pipe = Pipe(); process.standardOutput = pipe; process.standardError = pipe
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            process.terminationHandler = { result in
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                if result.terminationStatus == 0 { continuation.resume() }
                else { continuation.resume(throwing: NSError(domain: "Cognesia", code: Int(result.terminationStatus),
                    userInfo: [NSLocalizedDescriptionKey: String(data: data, encoding: .utf8) ?? "Research service startup failed."])) }
            }
            do { try process.run() }
            catch { process.terminationHandler = nil; continuation.resume(throwing: error) }
        }
    }

    func chooseLocalFile(model: Bool) {
        let panel = NSOpenPanel(); panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        panel.title = model ? "Choose GPT-OSS-20B GGUF model" : "Choose llama-server executable"
        panel.message = "Selecting a file fills the setup panel. Use Start local model to load it."
        if model { panel.allowedContentTypes = [UTType(filenameExtension: "gguf") ?? .data] }
        panel.beginSheetModal(for: window) { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            self?.dispatch(model ? "model-file" : "runtime-file", value: url.path)
        }
    }
    func openInstructions() {
        let panel = NSOpenPanel(); panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.plainText, .json, UTType(filenameExtension: "md") ?? .plainText]
        panel.title = "Open study instructions or exported trace"
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self, response == .OK, let url = panel.url else { return }
            do {
                let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                guard size <= 2_000_000 else { throw CocoaError(.fileReadTooLarge) }
                let data = try Data(contentsOf: url)
                let prompt: String?
                if url.pathExtension.lowercased() == "json" {
                    let trace = try JSONSerialization.jsonObject(with: data) as? [String: Any]
                    prompt = (trace?["study"] as? [String: Any])?["prompt"] as? String
                } else { prompt = String(data: data, encoding: .utf8) }
                guard let prompt, !prompt.isEmpty, prompt.count <= 16000 else {
                    throw NSError(domain: "Cognesia", code: 3, userInfo: [NSLocalizedDescriptionKey:"Choose UTF-8 instructions up to 16,000 characters, or a Cognesia trace containing study.prompt. Import fills the editor without running a study."])
                }
                dispatch("load-instructions", value: prompt)
            } catch { alert("Could not open instructions", error.localizedDescription) }
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "cognesiaResearch", message.frameInfo.isMainFrame,
              let url = message.frameInfo.request.url, isResearch(url),
              let data = message.body as? [String: Any], data["ready"] as? Bool == true else { return }
        if let commands = data["enabled"] as? [String: Bool] {
            enabled = commands.filter { key, _ in ResearchCommand(rawValue: key) != nil }
        }
        if let text = data["status"] as? String { window.subtitle = String(text.prefix(180)) }
    }
    private func isResearch(_ url: URL) -> Bool {
        url.scheme == "http" && ["127.0.0.1", "localhost"].contains(url.host ?? "") && url.port == port
    }
    private func isWorkbench(_ url: URL) -> Bool {
        url.scheme == "http" && ["127.0.0.1", "localhost"].contains(url.host ?? "") && url.port == viewerURL.port
    }
    private func external(_ url: URL) {
        if isWorkbench(url) { openWorkbench() }
        else if ["https", "http", "mailto"].contains(url.scheme?.lowercased() ?? "") { NSWorkspace.shared.open(url) }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if navigationAction.shouldPerformDownload && (isResearch(url) || url.scheme == "blob" || url.scheme == "data") { decisionHandler(.download) }
        else if isResearch(url) || url.absoluteString == "about:blank" { decisionHandler(.allow) }
        else { if navigationAction.navigationType == .linkActivated { external(url) }; decisionHandler(.cancel) }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url { external(url) }; return nil
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(navigationResponse.canShowMIMEType ? .allow : .download)
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard let url = webView.url, isResearch(url) else { return }
        ready = true; status.isHidden = true; window.makeFirstResponder(webView)
    }
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) { ready = false; enabled.removeAll() }
    private func failed(_ error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { showStatus("The research window could not load. Reconnect to recover it.\n\n\(error.localizedDescription)", loading: false) }
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { failed(error) }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { failed(error) }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { showStatus("The research window needs to reload. The model and experiments are separate services and may still be running.", loading: false) }
    private func alert(_ title: String, _ detail: String) {
        let panel = NSAlert(); panel.messageText = title; panel.informativeText = detail; panel.beginSheetModal(for: window)
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel(); panel.title = response.mimeType == "application/pdf" ? "Save Cognesia research paper" : "Export Cognesia research trace"
        panel.nameFieldStringValue = (suggestedFilename as NSString).lastPathComponent
        panel.canCreateDirectories = true
        panel.directoryURL = root.appendingPathComponent("runs", isDirectory: true)
        panel.beginSheetModal(for: window) { [weak self] response in
            guard response == .OK, let url = panel.url else { completionHandler(nil); return }
            let temporary = url.deletingLastPathComponent().appendingPathComponent(".cognesia-\(UUID().uuidString).download")
            self?.downloads[ObjectIdentifier(download)] = (temporary, url); completionHandler(temporary)
        }
    }
    func downloadDidFinish(_ download: WKDownload) {
        guard let target = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
        do {
            if FileManager.default.fileExists(atPath: target.final.path) { _ = try FileManager.default.replaceItemAt(target.final, withItemAt: target.temporary) }
            else { try FileManager.default.moveItem(at: target.temporary, to: target.final) }
            NSWorkspace.shared.activateFileViewerSelecting([target.final])
        } catch { alert("Could not finish export", "The completed download is preserved at:\n\(target.temporary.path)\n\n\(error.localizedDescription)") }
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        if let target = downloads.removeValue(forKey: ObjectIdentifier(download)) { try? FileManager.default.removeItem(at: target.temporary) }
        if (error as NSError).code != NSURLErrorCancelled { alert("Export failed", error.localizedDescription) }
    }
}
