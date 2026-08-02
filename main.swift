import SwiftUI
import AppKit
import UniformTypeIdentifiers

@main
struct TwoCapeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    
    var body: some Scene {
        WindowGroup {
            ContentView()
                .frame(minWidth: 620, maxWidth: 800, minHeight: 520, maxHeight: 720)
        }
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unified)
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}

@MainActor
class ConverterViewModel: ObservableObject {
    @Published var inputFolderPath: String = ""
    @Published var outputFolderPath: String = ""
    @Published var capeName: String = ""
    @Published var authorName: String = "Converted from Windows cursor theme"
    
    @Published var isTargeted: Bool = false
    @Published var isRunning: Bool = false
    @Published var logs: String = "等待开始转换...\n"
    @Published var statusMessage: String = "请选择包含 .ani / .cur 文件的文件夹"
    @Published var statusColor: Color = .secondary
    
    func selectInputFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "选择"
        panel.message = "请选择包含 .ani / .cur 光标文件的文件夹"
        
        if panel.runModal() == .OK, let url = panel.url {
            inputFolderPath = url.path
            if capeName.isEmpty {
                capeName = url.lastPathComponent
            }
            statusMessage = "就绪: 已选择 \(url.lastPathComponent)"
            statusColor = .secondary
        }
    }
    
    func selectOutputFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "选择导出目录"
        
        if panel.runModal() == .OK, let url = panel.url {
            outputFolderPath = url.path
        }
    }
    
    func handleFolderDrop(providers: [NSItemProvider], isInput: Bool) -> Bool {
        guard let provider = providers.first else { return false }
        
        provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { (item, error) in
            guard let data = item as? Data, let url = URL(dataRepresentation: data, relativeTo: nil) else { return }
            
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                Task { @MainActor in
                    if isInput {
                        self.inputFolderPath = url.path
                        if self.capeName.isEmpty {
                            self.capeName = url.lastPathComponent
                        }
                        self.statusMessage = "已放置文件夹: \(url.lastPathComponent)"
                        self.statusColor = .secondary
                    } else {
                        self.outputFolderPath = url.path
                    }
                }
            }
        }
        return true
    }
    
    func startConversion() {
        guard !inputFolderPath.isEmpty else { return }
        
        isRunning = true
        statusMessage = "正在转换中，请稍候..."
        statusColor = .accentColor
        logs = "[系统] 开始执行转换...\n[路径] 输入目录: \(inputFolderPath)\n"
        
        let inputPath = inputFolderPath
        let outputPath = outputFolderPath
        let name = capeName
        let author = authorName
        
        DispatchQueue.global(qos: .userInitiated).async {
            self.runPythonConverter(inputPath: inputPath, outputPath: outputPath, name: name, author: author)
        }
    }
    
    nonisolated private func runPythonConverter(inputPath: String, outputPath: String, name: String, author: String) {
        let scriptPath: String
        if let bundledScript = Bundle.main.path(forResource: "2cape", ofType: "py") {
            scriptPath = bundledScript
        } else {
            let currentDir = FileManager.default.currentDirectoryPath
            scriptPath = (currentDir as NSString).appendingPathComponent("2cape.py")
        }
        
        guard FileManager.default.fileExists(atPath: scriptPath) else {
            Task { @MainActor in
                self.logs += "[错误] 找不到 2cape.py 转换脚本: \(scriptPath)\n"
                self.statusMessage = "转换失败: 缺失 2cape.py 脚本"
                self.statusColor = .red
                self.isRunning = false
            }
            return
        }
        
        var arguments = [scriptPath, "--input", inputPath]
        
        if !outputPath.isEmpty {
            let outName = name.isEmpty ? (inputPath as NSString).lastPathComponent : name
            let destinationCape = (outputPath as NSString).appendingPathComponent("\(outName).cape")
            arguments.append(contentsOf: ["--output", destinationCape])
        }
        
        if !name.isEmpty {
            arguments.append(contentsOf: ["--name", name])
        }
        
        if !author.isEmpty {
            arguments.append(contentsOf: ["--author", author])
        }
        
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = arguments
        
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        
        let outHandle = pipe.fileHandleForReading
        outHandle.readabilityHandler = { handle in
            let data = handle.availableData
            if !data.isEmpty, let line = String(data: data, encoding: .utf8) {
                Task { @MainActor in
                    self.logs += line
                }
            }
        }
        
        do {
            try process.run()
            process.waitUntilExit()
            outHandle.readabilityHandler = nil
            
            let exitCode = process.terminationStatus
            Task { @MainActor in
                self.isRunning = false
                if exitCode == 0 {
                    self.statusMessage = "🎉 转换成功！已转换为 Mousecape 支持的 .cape 文件"
                    self.statusColor = .green
                    self.logs += "\n[成功] 转换完成，已转换为 Mousecape 支持的 .cape 文件！\n"
                } else {
                    self.statusMessage = "❌ 转换失败 (退出码 \(exitCode))"
                    self.statusColor = .red
                    self.logs += "\n[失败] 脚本运行异常，退出码: \(exitCode)\n"
                }
            }
        } catch {
            Task { @MainActor in
                self.isRunning = false
                self.statusMessage = "转换出错: \(error.localizedDescription)"
                self.statusColor = .red
                self.logs += "\n[错误] 进程启动失败: \(error.localizedDescription)\n"
            }
        }
    }
}

struct ContentView: View {
    @StateObject private var viewModel = ConverterViewModel()
    
    var body: some View {
        VStack(spacing: 16) {
            // Header
            HStack(spacing: 14) {
                if let iconPath = Bundle.main.path(forResource: "app_header_icon", ofType: "png"),
                   let nsImage = NSImage(contentsOfFile: iconPath) {
                    Image(nsImage: nsImage)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 48, height: 48)
                        .cornerRadius(10)
                        .shadow(color: .black.opacity(0.2), radius: 4, x: 0, y: 2)
                } else {
                    Image(systemName: "cursorarrow.and.square.on.square.dashed")
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 40, height: 40)
                        .foregroundColor(.accentColor)
                }
                
                VStack(alignment: .leading, spacing: 2) {
                    Text("2cape")
                        .font(.title2)
                        .fontWeight(.bold)
                    Text("将 Windows 光标包 (.ani / .cur) 整合转换为 Mousecape 支持的 .cape 文件")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                }
                Spacer()
            }
            .padding(.horizontal)
            .padding(.top, 12)
            
            Divider()
            
            // Drag & Drop / Input Section
            VStack(alignment: .leading, spacing: 12) {
                Text("1. 选择光标资源与导出路径")
                    .font(.headline)
                
                // Input folder selection card
                ZStack {
                    RoundedRectangle(cornerRadius: 10)
                        .fill(viewModel.isTargeted ? Color.accentColor.opacity(0.15) : Color(NSColor.controlBackgroundColor))
                        .overlay(
                            RoundedRectangle(cornerRadius: 10)
                                .stroke(viewModel.isTargeted ? Color.accentColor : Color.gray.opacity(0.3), style: StrokeStyle(lineWidth: viewModel.isTargeted ? 2 : 1, dash: [viewModel.isTargeted ? 0 : 5]))
                        )
                    
                    HStack(spacing: 12) {
                        Image(systemName: "folder.badge.plus")
                            .font(.system(size: 28))
                            .foregroundColor(viewModel.inputFolderPath.isEmpty ? .secondary : .accentColor)
                        
                        VStack(alignment: .leading, spacing: 4) {
                            Text(viewModel.inputFolderPath.isEmpty ? "拖拽文件夹到此处，或点击选择按钮" : "输入文件夹:")
                                .font(.body)
                                .fontWeight(viewModel.inputFolderPath.isEmpty ? .regular : .semibold)
                            
                            Text(viewModel.inputFolderPath.isEmpty ? "支持包含 .ani、.cur 或 .inf 的目录" : viewModel.inputFolderPath)
                                .font(.caption)
                                .foregroundColor(.secondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                        
                        Spacer()
                        
                        Button("浏览...") {
                            viewModel.selectInputFolder()
                        }
                        .controlSize(.regular)
                    }
                    .padding(14)
                }
                .onDrop(of: [.fileURL], isTargeted: $viewModel.isTargeted) { providers in
                    return viewModel.handleFolderDrop(providers: providers, isInput: true)
                }
                
                // Output folder selection
                HStack {
                    Text("导出位置:")
                        .font(.subheadline)
                        .frame(width: 75, alignment: .leading)
                    
                    TextField("与输入目录一致 (默认)", text: $viewModel.outputFolderPath)
                        .textFieldStyle(.roundedBorder)
                    
                    Button("选择...") {
                        viewModel.selectOutputFolder()
                    }
                }
            }
            .padding(.horizontal)
            
            // Metadata settings
            VStack(alignment: .leading, spacing: 10) {
                Text("2. 主题元数据 (选填)")
                    .font(.headline)
                
                HStack(spacing: 16) {
                    HStack {
                        Text("Cape 名称:")
                            .font(.subheadline)
                            .frame(width: 75, alignment: .leading)
                        TextField("自动采用文件夹名称", text: $viewModel.capeName)
                            .textFieldStyle(.roundedBorder)
                    }
                    
                    HStack {
                        Text("作者信息:")
                            .font(.subheadline)
                            .frame(width: 65, alignment: .leading)
                        TextField("作者", text: $viewModel.authorName)
                            .textFieldStyle(.roundedBorder)
                    }
                }
            }
            .padding(.horizontal)
            
            // Action Button & Status
            HStack {
                Text(viewModel.statusMessage)
                    .font(.subheadline)
                    .foregroundColor(viewModel.statusColor)
                
                Spacer()
                
                Button(action: { viewModel.startConversion() }) {
                    HStack {
                        if viewModel.isRunning {
                            ProgressView()
                                .controlSize(.small)
                                .padding(.trailing, 4)
                        } else {
                            Image(systemName: "arrow.triangle.2.circlepath")
                        }
                        Text(viewModel.isRunning ? "正在转换..." : "开始转换 .cape")
                            .fontWeight(.semibold)
                    }
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                }
                .buttonStyle(.borderedProminent)
                .disabled(viewModel.inputFolderPath.isEmpty || viewModel.isRunning)
            }
            .padding(.horizontal)
            
            // Console / Log Area
            VStack(alignment: .leading, spacing: 6) {
                Text("转换日志:")
                    .font(.caption)
                    .foregroundColor(.secondary)
                
                ScrollViewReader { proxy in
                    ScrollView {
                        Text(viewModel.logs)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundColor(Color(NSColor.textBackgroundColor) == Color.white ? .black : Color(NSColor.textColor))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(10)
                            .id("logBottom")
                    }
                    .background(Color(NSColor.textBackgroundColor))
                    .cornerRadius(8)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color.gray.opacity(0.2), lineWidth: 1)
                    )
                    .onChange(of: viewModel.logs) { _ in
                        withAnimation {
                            proxy.scrollTo("logBottom", anchor: .bottom)
                        }
                    }
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 12)
        }
    }
}
