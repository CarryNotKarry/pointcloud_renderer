# 交互式论文点云工作台

这套新入口与原有 CLI 并存。v2 默认交付**独立 PDF / JPG / PNG 素材**，适合在 WPS 中自由拼接；多方法 comparison 作为可选参考图保留。

## 启动

```bash
cd pointcloud_renderer
python3 -m venv .venv   # 已有 .venv 时不需要重建
source .venv/bin/activate
python -m pip install -r requirements.txt
python render_workbench.py
```

浏览器会打开 `http://127.0.0.1:8765`。不需要额外的 Qt、Polyscope、Node.js 或前端构建步骤，也没有 CDN 依赖。浏览器关闭后可以重新打开这个地址；停止服务在启动终端按 Ctrl+C。

先体验完整功能：

```bash
python render_workbench.py --demo
```

演示中的 `Demo-Input` / `Demo-Dense` 只是同一合成点云的不同采样密度，不代表任何论文方法。启动时带 `--demo` 会将当前工作目录内的会话替换成演示会话；真实工作建议使用另一个 `--workspace`。

```bash
python render_workbench.py --demo --workspace workbench_data/demo
python render_workbench.py --workspace workbench_data/my_paper
```

## 加载真实实验目录

点击「加载方法目录」，每行填一组名称与目录：

```text
Input | /absolute/path/results/Input
RepKPU | /absolute/path/results/RepKPU
Grad-PU | /absolute/path/results/Grad-PU
APU-LDI | /absolute/path/results/APU-LDI
Ours | /absolute/path/results/Ours
GT | /absolute/path/results/GT
```

可填写 `panda.xyz, hand.xyz` 筛选物体，留空则收集所有目录中的文件名并集。脚本递归扫描 `.xyz`，按完全相同的文件名匹配；建议各方法使用一致的大小写。重复文件名会提示并稳定选取第一个路径，缺失方法会保留空列和 Missing 标记。

也可从命令行直接加载：

```bash
python render_workbench.py \
  --method_dirs results/Input results/RepKPU results/Grad-PU results/Ours results/GT \
  --method_names Input RepKPU Grad-PU Ours GT \
  --targets panda.xyz hand.xyz \
  --workspace workbench_data/my_paper
```

加载新目录会替换当前会话，先用「保存会话」另存重要设置。目录内的源数据不被修改。会话保存绝对输入路径；把会话迁移到另一台机器后，需要恢复这些数据路径或编辑会话中的路径。

## 视角、图层和公平比较

1. 点击左侧物体名称切换当前编辑物体。物体左侧勾选框决定最终论文图包含哪些行。
2. 勾选方法决定显示/导出哪些列。↑↓ 修改列顺序；双击方法名称修改论文标签。
3. 「旋转视角」模式中拖动点云图，浏览器实时投影真实 XYZ 坐标。松开后用同一个完整正交相机恢复 VTK 高清光照。滚轮可实时缩放；数字框可精确设置方位角、仰角、滚转、缩放和平移。拖动阶段使用轻量球形点预览，不显示 soft shadow；超大点云每方法最多预览 20000 个确定性采样点，正式输出仍使用全部原始点。
4. 「并排比较」用于论文选景；「图层叠加」把已选图层的同视角图像做 multiply/alpha 合成，用于辅助检查轮廓对齐。叠加图是屏幕图像合成，不提供不同方法之间的 3D 深度遮挡判断；正式导出始终使用独立方法列。
5. 点击「保存视角」得到 camera JSON；「载入视角」也兼容旧 CLI 的 camera JSON。

相机始终为正交投影。GT 优先作为归一化参考，没有 GT 则选 Ours，否则使用第一个可读方法。所有方法共用参考中心和尺度；自动取景使用所有已加载方法的联合范围。球半径在每个物体首次取景时统一估计并固定，再统一乘以 `size_scale`。显隐、排序和切换物体不会重新选择参考或半径。

这些输入必须原本就处于一致的坐标系；程序不做 ICP、旋转对齐或按方法单独缩放。来源已经各自随机旋转的结果应先配准。方法输出的几何范围不同也可能导致底部位置不同，这是几何差异，不会通过独立平移去掩盖。

每个物体保存独立的视角、框、颜色和指标。统一风格控制颜色、背景、球大小、光照、阴影；「当前物体颜色」可以实现附件中不同物体使用不同颜色的排版。

点大小可通过数字框或滑块调整，滑动时即时预览。它控制点球大小，缩放控件控制整个物体大小；论文公平比较推荐点大小倍率 0.85–1.15，超出时会 warning，但仍允许探索，同一物体所有方法共享同一最终半径。所有实际相机向量、半径、倍率、背景、光照、阴影、颜色、ROI 和导出参数都存入同一个 `session.json`。

## 局部框：建议直接在工作台完成

先确定相机，再点击「绘制局部框」，在任一方法图上拖出矩形。它会同步应用到当前物体的全部方法，每个物体最多四个框，下方即时显示局部预览。

画错后可用「删除」或「编辑像素」。新增、删除、编辑和清空框均可用「撤销框选操作」或 Ctrl/⌘+Z 撤销，保留最近 30 次框操作，重开会话也能恢复。输入框获得焦点时快捷键保留文本编辑语义。按 Esc 取消尚未松手的绘框。已有框也会一起导出为带框图、透明 `roi_frames.png` 图层，以及 `regions.json` 坐标文件。

点击「按像素添加框」或已有框的「编辑像素」可以精确输入：

- 参考图像边长，例如 `1600`；
- 左上角 `X, Y`；
- 框的宽度和高度。

图像坐标原点在左上角，只包含正方形渲染区域，不包含浏览器标签、方法标题和页面边框。框以 `[0,1]` 相对坐标保存，因此浏览器缩放、Retina 像素比和最终分辨率不会改变对应区域。导出的 manifest 记录最终像素框，右边界和下边界为不包含端点的 Pillow 裁图格式。

如果使用外部截图软件，推荐从导出的干净单图上读取像素，再把该单图边长及选框数值填入工作台。直接读取整张屏幕截图的坐标需要自行扣掉页面偏移并考虑系统缩放，容易错位。

改变相机后，框仍固定在原来的**屏幕区域**，不会跟踪一个 3D 表面。因此应复核或重画；这与论文中按图像局部放大的定义一致。

## 导出和会话复用

每次修改都会自动保存 `workbench_data/session.json`。停止/重启不传新数据参数时会恢复该会话；「保存会话」允许另存多个方案：

```bash
python render_workbench.py --session /path/to/my_session.json
```

「导出论文图」默认将所选物体和方法输出为独立素材，每次导出使用新目录：

```text
workbench_data/exports/时间戳/
  index.html
  assets.zip
  session.json
  manifest.json
  00_panda/
    camera.json
    regions.json
    roi_frames.png
    00_Input_clean.{pdf,jpg,png}
    00_Input_annotated.{pdf,jpg,png}
    00_Input_roi_1.{pdf,jpg,png}
    00_Input_roi_1_framed.{pdf,jpg,png}
    ...
  01_hand/
    ...
```

- clean/annotated 单图默认 1600×1600；各方法严格共用视角和正交尺度，不单独裁边。
- clean 不带框，annotated 带框；ROI 从干净单图直接裁出，另外提供带边框的 ROI。JPG 用质量 98、无色度降采样保存；PNG 是无损版，适合放大查看稀疏点和复核像素。
- 每一种素材各有一个单页 PDF 和一张 JPG/PNG，图像内不加入方法名称或指标。
- ROI 保持原始裁图分辨率和长宽比；非常小的选框没有足够像素时，可以增大单图分辨率后重新导出。
- 「额外生成拼接参考图」默认不选，勾选后才输出旧版 comparison，在单独目录中保存。界面中的指标文字只影响可选 comparison，不进入独立素材。
- PDF 嵌入栅格图，保持像素与长宽比，不是点云矢量几何 PDF。
- 每次导出使用新时间戳目录，保留过去的图与对应完整设置。

导出作为后台任务执行。进度条按已完成的渲染、文件保存、参数写入和打包步骤更新，不模拟按时间递增。单个大点云渲染期间数值可能暂时停留在当前步骤。导出完成会显示完整保存路径、浏览素材链接和 ZIP 下载；失败会显示错误。执行期间界面暂时锁定编辑，保证导出使用同一套设置。

WPS 中建议批量插入 `*_clean.jpg` 或 `*_annotated.jpg`，锁定长宽比、设置相同宽度，再使用“顶端对齐 / 横向分布”；局部区域使用 `*_roi_N_framed.jpg`。若需要避免 JPG 压缩，则选择同名 PNG；PDF 留作论文排版或归档。方法标题、指标和行列布局由你在文档中自由安排。

manifest 包含输入路径、归一化、相机、最终半径、颜色/光照/阴影参数、ROI 像素边界、手动指标和文件路径。

同一份会话也可在无界面时重导出：

```bash
python render_workbench.py --session /path/to/session.json \
  --workspace workbench_data/reproduce --export-only --size 1600 --cell 480
```

默认导出独立 PDF/JPG/PNG。额外拼图加 `--comparison`，关闭 PDF 加 `--no-pdf`。

## 运行环境与实际边界

界面是本地网页，所有点云读取和渲染在本机完成。PyVista/VTK 离屏渲染在独立进程的主线程执行；前端不会上传点云到外部服务。仅监听 `127.0.0.1`。

静止预览使用 480 px 的 sphere glyph 渲染，正式导出使用更高分辨率。拖动中采用浏览器本地轻量几何投影以实时反馈，并在松开后恢复 VTK 最终效果；两者共用同一相机，材质观感会略有不同。速度随点数、方法数、浏览器和显卡变化，未承诺固定帧率。重复的 VTK 取景会命中磁盘缓存。

Linux 无桌面环境需要 VTK 的 EGL/OSMesa 支持，或使用 `xvfb-run -a python render_workbench.py --no-browser`。远程服务器场景可以通过 SSH 转发工作台端口到本机浏览器。首次打开一个物体时会缓存读取数据，若外部结果文件发生变化，重新加载会话/方法目录以重新读取。

常用参数：`--port 8765`、`--no-browser`、`--workspace path`。工作目录中的 `cache/` 是可再生预览/渲染缓存；`exports/`、`cameras/`、`session.json` 是用户成果，清理缓存时不要误删它们。

## 仓库和验证

旧 CLI 已保存为 Git 标签 `cli-v1`。工作台使用新文件，不改变旧单图/网格/benchmark 命令的行为。Git 已排除虚拟环境、运行数据和输出图；上传 GitHub 时推送源代码和需要的 tag 即可。

```bash
python -m unittest test_workbench -v
```

回归测试覆盖显隐不改变共享相机/半径、相机会话重开、精确无框像素裁图、缺失列保留及无效框拒绝。实际验收还需要启动工作台验证浏览器拖框、视角刷新、PNG/PDF 输出。
