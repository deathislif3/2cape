# 2cape - Windows ANI 到 Mousecape (.cape) 光标转换器

![2cape Logo](app_header_icon.png)

**2cape** 是一款专为 macOS 打造的高效、轻量级光标格式转换工具。它可以将 Windows 的 `.ani` (动画光标) 和 `.cur` (静态光标) 资源整合转换为 [Mousecape](https://github.com/sdmj76/Mousecape-swiftUI) 支持的 `.cape` 鼠标主题文件。

---

## ✨ 核心特性

- **零依赖转换**：内置 Python 转换引擎，直接解构 RIFF/ACON、DIB 与嵌入式 PNG 位图。
- **动画光标支持**：自动提取 ANI 多帧动画并拼接为符合 Mousecape 规范的垂直 Sprite Sheet。
- **智能角色识别**：
  - 优先读取 Windows `.inf` 安装文件注册表方案进行 17 种标准光标角色精准绑定。
  - 支持按文件名关键字与别名词典模糊匹配。
- **macOS 原生 GUI 应用**：
  - 基于 SwiftUI 构建，支持暗色模式与原生界面。
  - 支持拖拽文件夹 (Drag & Drop) 或弹出原生框选取文件。
  - 实时显示控制台转换日志与状态反馈。

---

## 🚀 使用方法

### 方法一：使用 GUI 桌面应用 (`2cape.app`)

1. 双击运行 `2cape.app`。
2. 将包含 `.ani` / `.cur` / `.inf` 的 Windows 指针文件夹拖入应用窗口（或点击“浏览...”选择）。
3. （可选）自定义 Cape 名称与作者信息。
4. 点击 **“开始转换 .cape”** 按钮。导出成功后双击生成的 `.cape` 文件即可直接导入 Mousecape。

### 方法二：使用命令行 (`2cape.py`)

在终端中运行 Python 脚本：

```bash
# 转换指定目录下的光标
python3 2cape.py --input ./MyTheme --name "My Theme"

# 指定导出路径
python3 2cape.py --input ./MyTheme --output ~/Desktop/MyTheme.cape
```

---

## 🛠 构建与编译

环境要求：macOS 12.0+

```bash
# 赋予脚本执行权限并编译生成 2cape.app
chmod +x build_app.sh
./build_app.sh
```

---

## 📄 开源许可

[MIT License](LICENSE)
