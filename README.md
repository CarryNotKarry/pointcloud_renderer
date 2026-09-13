# 点云论文渲染工具

把点云文件渲染成适合论文展示的图片：浅蓝小球、干净背景、正交视角、柔和阴影。不需要 Blender。

本项目包含两种使用方式：

- **命令行版**：批量生成单图、多视角图和方法对比图。
- **交互工作台**：在浏览器中拖动视角、调节点大小、框选局部，满意后逐张导出。推荐日常使用。

## 安装

建议使用 Python 3.10 或更高版本。在项目目录执行（苹果电脑或 Linux）：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

安装依赖时不要漏掉 `-r`。以后重新打开终端，先进入项目目录，再执行 `source .venv/bin/activate`。

## 命令行版

```bash
python generate_demo_xyz.py
python render_single.py --input demo_data/box.xyz --output outputs/box.png --shadow_mode soft
python render_grid.py --input_dir demo_data --output outputs/grid.png --shadow_mode soft
```

结果保存在 `outputs/`。更多参数和多个方法的批量比较见[命令行详细说明](CLI_GUIDE.md)。

## 交互工作台

首次体验，使用独立的示例工作目录：

```bash
python render_workbench.py --demo --workspace workbench_data/quickstart
```

打开 <http://127.0.0.1:8765/>。下次继续上次的操作，不要再加 `--demo`：

```bash
python render_workbench.py --workspace workbench_data/quickstart
```

注意：`--demo` 会重新初始化示例会话。端口被占用时，可以直接打开现有页面，或加 `--port 8766` 启动另一个工作台。

使用流程：

1. 加载各方法目录，同一物体使用相同文件名，例如 `panda.xyz`。
2. 拖动视角，调节点大小和画面占比；同一物体的不同方法共用相机与点半径。
3. 框选局部。框错了可删除、修改像素坐标或撤销；正在画的框可按退出键取消。
4. 保存会话，将相机、点大小和局部框等参数一起保存到 JSON 文件。
5. 点击导出，等待进度完成，页面会显示保存位置和下载链接。

默认分别输出 **PDF、JPG、PNG**：无框原图、带框原图、局部截图、带框局部图，不强制拼成一张总图。框的位置和相机参数也会保存。PDF 是高清图片封装，不是矢量点云。

结果位于所选工作目录的 `exports/` 下。可以把独立图片放入 WPS，设置相同宽度，再使用对齐和横向分布功能排版。完整操作见[工作台详细说明](WORKBENCH.md)。

## 注意事项

- 点大小建议只在默认值的 0.85～1.15 倍之间微调，不要按方法分别调节。
- 软阴影通过地面投影、二维遮罩、高斯模糊和低透明度灰色叠加生成，是论文展示用的近似阴影，并非物理真实阴影。
- 最终图片由 PyVista 和 VTK 离屏渲染。无桌面的 Linux 仍需要可用的离屏图形后端，配置见详细说明。
- 私有点云、工作会话和导出图片不要上传到公开仓库。

## 上传到 GitHub

推荐两个工具放在同一个仓库。操作步骤及分成两个仓库的办法见[中文上传指南](GITHUB_UPLOAD.md)。

历史标签：`cli-v1` 为原命令行版，`workbench-v1` 为初版工作台，`workbench-v2` 为增强工作台。当前主分支包含两种工具及最新说明。
