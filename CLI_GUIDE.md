# 命令行渲染详细说明

新增 **交互式工作台 v2**：运行 `python render_workbench.py --demo`，集中管理多个方法/物体，实时拖动视角、调节点大小、保存/撤销局部框，并默认逐张导出独立 PDF / JPG / PNG（原图、带框图、局部图）。提供导出进度、完整 JSON 和 ZIP；多行 comparison 可选。完整操作说明见 [WORKBENCH.md](WORKBENCH.md)。原有命令行版本保存在 Git 标签 `cli-v1`。

一个面向 CV/3D 论文 qualitative figure 的纯 Python 点云渲染工具。主体由 PyVista/VTK 离屏渲染，网格排版与连续软阴影由 Pillow 完成；不使用 Blender，也不使用 Matplotlib 作为最终渲染器。

默认风格为：极浅灰白底、浅蓝小球点、正交投影、固定 3/4 视角、柔和三点布光、连续低透明度软阴影和自动统一构图。

## 主要特性

- 读取空白分隔的 `x y z`，兼容额外列、空行和 `#` 注释
- 按包围盒中心化，最大边长统一缩放到 1
- `iso/front/side/top` 固定正交相机
- 根据相机投影包围盒自动取景，各 shape 使用一致 padding 和画面占比
- 根据归一化尺度和稳健近邻间距自动估计点半径
- `--size_scale` 仅提供 0.85～1.15 的弱视觉微调，避免破坏比较公平性
- 默认真实 sphere glyph；另有 `fast` 球形点精灵和 `smooth` Gaussian 点模式
- 主光、补光和轻微轮廓光，提供 `soft/studio` 两套布光
- 顶部略亮、底部略深的克制色调变化，增强形体层次
- `soft` 阴影使用 2D alpha mask + Gaussian blur，不显示灰色投影点
- 批量输出整齐的 comparison grid，可选文件名标签
- 自动匹配多个方法目录中的同名 object，输出 preview、单图、comparison、PDF 和 manifest
- 支持 azimuth/elevation/roll 和相机 JSON 保存、加载、严格复用
- 支持白底、透明 PNG、自定义颜色和多种颜色主题

## 安装

建议使用 Python 3.10 或更高版本。项目已使用 Python 3.12、PyVista 0.48.4 和 VTK 9.6.2 实际验证。

```bash
cd pointcloud_renderer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
```

Open3D 不是必需依赖；XYZ 读写使用 NumPy，主体渲染由 PyVista/VTK 完成。

## 推荐命令

以下命令均在 `pointcloud_renderer/` 目录执行：

```bash
python generate_demo_xyz.py

python render_single.py \
  --input demo_data/box.xyz \
  --output outputs/box.png \
  --shadow_mode soft

python render_grid.py \
  --input_dir demo_data \
  --output outputs/grid.png \
  --shadow_mode soft \
  --labels

python render_benchmark.py \
  --root_dir results \
  --methods Input RepKPU Grad-PU APU-LDI Ours GT \
  --target panda.xyz \
  --output_dir outputs/panda
```

`soft` 已是默认阴影模式，因此不写 `--shadow_mode` 也会得到推荐论文风格。

## 多方法 benchmark 工作流

`render_benchmark.py` 面向论文 qualitative comparison：它按照命令行给出的顺序遍历方法目录，自动查找同名 `.xyz`，并为同一个 object 强制复用完全相同的归一化、正交相机、球半径、光照、阴影参数和背景。某个方法缺文件时只输出 warning，其他方法和其他 object 会继续处理。

### 方式 A：直接给出方法目录

```bash
python render_benchmark.py \
  --method_dirs \
    results/Input \
    results/RepKPU \
    results/Grad-PU \
    results/APU-LDI \
    results/Ours \
    results/GT \
  --method_names Input RepKPU Grad-PU APU-LDI Ours GT \
  --target panda.xyz \
  --output_dir outputs/panda
```

`--method_names` 同时是稳定的方法标识；如果省略，就使用各目录名。需要显示不同标签时再加：

```bash
--method_labels Input "RepKPU" "Grad-PU" "APU-LDI" "Ours" "Ground Truth"
```

方法顺序就是 comparison 中从左到右、从上到下的顺序。

### 方式 B：根目录 + 方法名

目录为 `results/Input/panda.xyz`、`results/Ours/panda.xyz` 等结构时：

```bash
python render_benchmark.py \
  --root_dir results \
  --methods Input RepKPU Grad-PU APU-LDI Ours GT \
  --target panda.xyz \
  --output_dir outputs/panda
```

脚本先检查 `方法目录/target`，找不到时再按文件名递归查找方法目录。因此也兼容 `results/GT/test/panda.xyz` 这类多一层的结果结构；若出现多个同名文件，会 warning 并稳定选择路径最短、字典序最靠前的一个。

### 方式 C：一次处理多个 object

```bash
python render_benchmark.py \
  --root_dir results \
  --methods Input RepKPU Grad-PU APU-LDI Ours GT \
  --targets panda.xyz tiger.xyz elephant.xyz \
  --output_dir outputs/batch
```

单个 target 直接把内容写入 `--output_dir`。多个 target 则分别写入 `outputs/batch/panda/`、`outputs/batch/tiger/`、`outputs/batch/elephant/`。

每个 object 的标准输出结构为：

```text
outputs/panda/
├── preview/
│   ├── panda_preview_sheet.png
│   ├── panda_preview_sheet.pdf
│   ├── view_00.png
│   ├── view_00_camera.json
│   └── ...
├── singles/
│   ├── Input.png
│   ├── RepKPU.png
│   └── ...
├── comparison/
│   ├── panda_comparison.png
│   └── panda_comparison.pdf
├── cameras/
│   └── panda_view_best.json
└── manifest.json
```

### 推荐的论文视角选择流程

第一步只生成 8 个候选视角和 preview sheet：

```bash
python render_benchmark.py \
  --root_dir results \
  --methods Input RepKPU Grad-PU APU-LDI Ours GT \
  --target panda.xyz \
  --output_dir outputs/panda \
  --preview_only
```

检查 `outputs/panda/preview/panda_preview_sheet.png`，记下满意的 `view_XX` 编号。第二步用该编号生成最终对比图，例如选择 `view_05`：

```bash
python render_benchmark.py \
  --root_dir results \
  --methods Input RepKPU Grad-PU APU-LDI Ours GT \
  --target panda.xyz \
  --output_dir outputs/panda \
  --camera_index 5
```

脚本会把最终相机保存到 `outputs/panda/cameras/panda_view_best.json`。之后复用该相机并跳过 preview：

```bash
python render_benchmark.py \
  --root_dir results \
  --methods Input RepKPU Grad-PU APU-LDI Ours GT \
  --target panda.xyz \
  --output_dir outputs/panda \
  --load_camera outputs/panda/cameras/panda_view_best.json \
  --skip_preview
```

也可以直接加载某个候选文件，如 `preview/view_05_camera.json`。相机 JSON 除了完整正交相机，还保存参考方法的 center/scale；加载后会复用这套归一化，避免因缺少某个方法或重新运行而产生取景漂移。对于多个 object，`--load_camera` 可以指向包含 `{object}` 的路径模板，或指向 batch 输出根目录。

如果已有明确角度，也可用 `--azimuth --elevation --roll` 直接拟合并保存最终相机。它们不能和 `--load_camera` 同时使用。

### 单独生成多视角 preview

```bash
python render_multiview.py \
  --input results/GT/panda.xyz \
  --output_dir outputs/panda_preview \
  --camera_index 0
```

自定义候选角度使用 `AZIMUTH,ELEVATION[,ROLL]`：

```bash
python render_multiview.py \
  --input results/GT/panda.xyz \
  --output_dir outputs/panda_preview \
  --views="-52,27;-20,25;20,25;52,27"
```

### PNG、PDF 与自动裁边

benchmark 默认同时导出 preview/comparison 的 PNG 和 PDF。PDF 页面尺寸与 PNG 长宽比一致，像素不会在导出阶段重采样；`--pdf_dpi` 只控制页面物理尺寸。使用 `--no_pdf` 可关闭 PDF。

comparison 和 preview sheet 默认只裁掉最外层的均匀背景，并保留 `--crop_padding` 指定的像素留白。各方法内部 panel 不单独裁切，因此同一 object 的画面占比和底部位置仍保持一致。使用 `--no_autocrop` 可保留完整画布。

### 颜色模式

默认 `--color_mode unified --theme blue`，所有方法使用同一种浅蓝色，最适合严谨、简洁的论文比较。统一主题支持：

```text
blue / grayblue / teal / orange / purple
```

需要区分方法时：

```bash
python render_benchmark.py \
  --root_dir results \
  --methods Input RepKPU Grad-PU APU-LDI Ours GT \
  --target panda.xyz \
  --output_dir outputs/panda_colors \
  --color_mode per_method \
  --method_color_config configs/colors.json
```

颜色 JSON 可以是平面对象，也可以放在 `methods` 字段中：

```json
{
  "methods": {
    "Input": "#B8BEC8",
    "RepKPU": "#E4B382",
    "Grad-PU": "#91C4A8",
    "APU-LDI": "#B1A0D0",
    "Ours": "#90AEDD",
    "GT": "#5F708A"
  }
}
```

### manifest.json

每个 object 的 manifest 记录：object/target、按顺序排列的方法及实际输入路径、缺失状态、点数、方法颜色、参考方法、归一化 center/scale、最佳 camera JSON、完整相机向量、最终共享半径、`size_scale`、光照/阴影/背景参数、全部 preview 的 azimuth/elevation/roll，以及所有输出路径。它可以直接作为论文图复现实验记录。

推荐顺序是：先 `--preview_only`，再选 `--camera_index`，然后用保存的 camera 生成 comparison，最后使用默认 PDF 输出进入论文排版。

## 默认视觉参数

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| 分辨率 | `1600x1600` | 单图高清 PNG |
| `--color` | `#90AEDD` | 浅蓝点云 |
| `--bg_color` | `#FAFAFC` | 极浅灰白背景 |
| `--sphere_radius` | 自动 | 根据尺度和点密度估计 |
| `--size_scale` | `1.0` | 推荐仅在 `0.85~1.15` 内弱调节 |
| `--sphere_resolution` | `12` | glyph 球细分 |
| `--shadow_mode` | `soft` | 连续图像空间软阴影 |
| `--shadow_opacity` | `0.11` | 阴影最大 alpha |
| `--shadow_blur` | `32` | 以 1600 px 图片为参考的模糊半径 |
| `--light_preset` | `soft` | 柔和论文布光 |
| `--padding` | `0.12` | 自动取景边距比例 |

## 阴影模式

### soft（默认、推荐）

处理流程：

```text
3D 点云投影到 ground plane
→ 正交相机投影到 2D
→ 栅格化 alpha mask
→ Gaussian blur
→ 以低透明度灰色在主体图层下方叠加回图像
```

它不会把投影后的每个点直接显示成灰球，因此阴影连续、淡且没有颗粒感。阴影由以下参数控制：

```bash
--shadow_mode soft
--shadow_opacity 0.11
--shadow_blur 32
```

`--shadow_blur` 以 1600 px 为参考；渲染较小 grid cell 时会按分辨率自动缩放，保证单图和网格观感一致。

这是面向论文插图的近似阴影，而不是光线追踪或物理真实阴影。它的目的只是以稳定、克制的方式提供接地感和空间层次，不用于表达真实光照测量结果。

### simple

保留快速的 3D 点投影方式，适合调试或追求速度：

```bash
python render_single.py \
  --input demo_data/box.xyz \
  --output outputs/box_simple.png \
  --shadow_mode simple
```

### none

完全关闭阴影：

```bash
python render_single.py \
  --input demo_data/box.xyz \
  --output outputs/box_clean.png \
  --shadow_mode none
```

旧参数 `--shadow` 仍可使用，并等价于 `--shadow_mode soft`。

## 主体渲染与光照

默认 `glyph` 模式把每个点实例化为低多边形真球体，适合数千点规模的论文图：

```bash
python render_single.py \
  --input demo_data/wedge.xyz \
  --output outputs/wedge_studio.png \
  --mode glyph \
  --light_preset studio \
  --view iso
```

布光模式：

- `soft`：较均匀、低镜面高光，适合论文主图。
- `studio`：主光和轮廓光更明确，顶面/侧面反差略强。

高点数点云可使用：

```bash
python render_single.py \
  --input cloud.xyz \
  --output outputs/cloud_fast.png \
  --mode fast \
  --point_size 6
```

三种主体模式：

- `glyph`：真实球几何，默认质量最高。
- `fast`：VTK 球形 point sprite，适合数万点。
- `smooth`：柔和 Gaussian point，适合稠密视觉效果。

## 自动点大小与比较公平性

默认不需要指定 `--sphere_radius`。程序会先对点云做 center + normalize，再从最多 1024 个查询点和 8192 个参考点估计中位最近邻间距，以点云尺度和密度得到一个保守半径。估计值有窄范围限制，不会因为局部离群点或点数变化而无限放大或缩小。

只需要轻微调整视觉大小时使用：

```bash
python render_single.py \
  --input real_pugan.xyz \
  --output outputs/real_pugan.png \
  --size_scale 0.95
```

推荐范围是 `0.85~1.15`。超出此范围仍会执行，但程序会输出 warning，提醒该设置可能削弱 qualitative comparison 的公平性。`render_grid.py` 会先计算所有输入的自动半径中位数，再给每个 panel 使用完全相同的最终半径和 `size_scale`。

`--sphere_radius` 仍作为专家级显式覆盖保留；显式半径同样会乘以 `--size_scale`。

## 自动构图与 padding

默认情况下，任意 XYZ 都会先做包围盒中心化，再按最大边长归一化。未指定 `--camera_scale` 时，程序会把点云及其阴影投影到当前视角，计算二维包围盒，并按照 `--padding` 自动设置正交范围；相机距离也会根据归一化后的三维包围盒设置到安全值。由于正交投影的画面占比主要由 `parallel_scale` 决定，因此不同 shape 可保持稳定占比，同时避免近远裁剪问题。

```bash
python render_single.py \
  --input demo_data/thin_plate.xyz \
  --output outputs/thin_plate.png \
  --padding 0.12
```

需要严格固定正交范围时可显式设置：

```bash
--camera_scale 0.72
```

数值越大，物体越小、留白越多。

## 手动视角与相机 JSON

可以用角度覆盖 `--view` 对应的默认方向：

```bash
python render_single.py \
  --input real_pugan.xyz \
  --output outputs/real_pugan_view.png \
  --azimuth -35 \
  --elevation 24 \
  --roll 0 \
  --save_camera cameras/real_pugan.json
```

- `--azimuth`：绕世界 z 轴的方位角，单位为度。
- `--elevation`：相机仰角，范围 `[-90, 90]` 度。
- `--roll`：绕观察方向的画面滚转角，单位为度。

相机 JSON 保存完整的正交相机 `position`、`focal_point`、`view_up` 和 `parallel_scale`。后续结果可直接加载：

```bash
python render_single.py \
  --input another_method_same_object.xyz \
  --output outputs/another_method.png \
  --load_camera cameras/real_pugan.json
```

加载相机后会跳过角度覆盖和自动取景，确保视角、滚转、平移和正交缩放完全一致。`--load_camera` 不能与 `--azimuth`、`--elevation`、`--roll` 或 `--camera_scale` 同时使用。

## 网格图与多方法公平对比

不同类别 shape 推荐默认独立归一化和自动构图：

```bash
python render_grid.py \
  --input_dir demo_data \
  --output outputs/grid.png \
  --columns 3 \
  --cell-width 720 \
  --cell-height 720 \
  --padding 0.12 \
  --shadow_mode soft \
  --labels
```

同一个 shape 的多个方法结果推荐 `shared`：

```bash
python render_grid.py \
  --input_dir results/chair_001 \
  --output outputs/chair_001_methods.png \
  --normalization shared \
  --columns 5 \
  --shadow_mode soft \
  --labels
```

`shared` 会让所有文件共用同一个三维中心、尺度、相机位置、焦点和正交范围，避免因各 panel 自动缩放而影响公平比较。

还可以把这套共享相机保存下来：

```bash
python render_grid.py \
  --input_dir results/chair_001 \
  --output outputs/chair_001_methods.png \
  --normalization shared \
  --save_camera cameras/chair_001.json
```

之后用 `--load_camera cameras/chair_001.json` 复用。多文件 grid 只有在 `--normalization shared` 或已经提供 `--load_camera` 时才能保存单一相机，防止误把多个独立自动取景相机当成一个公平相机。

归一化选项：

- `per-shape`：默认；每个文件独立中心化和缩放，适合不同物体类别。
- `shared`：所有文件使用同一个变换和同一相机，适合同一对象的多方法结果。
- `none`：保留原始坐标。

文件按名称稳定排序；`--recursive` 可递归读取子目录。

## 透明背景与颜色

```bash
python render_single.py \
  --input demo_data/cylinder.xyz \
  --output outputs/cylinder_rgba.png \
  --transparent-background \
  --shadow_mode soft
```

透明输出会保留主体抗锯齿 alpha 和半透明阴影。自定义风格：

```bash
python render_single.py --input cloud.xyz --output outputs/green.png --theme green
python render_single.py --input cloud.xyz --output outputs/custom.png --color '#A8C7FA' --bg_color white
```

内置主题为 `blue`、`grayblue`、`teal`、`green`、`orange` 和 `purple`；显式 `--color` 会覆盖主题。benchmark 的推荐主题集合不包含语义接近的 `green`，以保持选项更克制。

## 无显示器服务器

脚本始终使用 `off_screen=True`，并设置 `PYVISTA_OFF_SCREEN=true`。EGL/OSMesa VTK 环境可直接运行。若 Linux 上的 VTK wheel 仍依赖 X server，可使用：

```bash
xvfb-run -a python render_single.py \
  --input demo_data/box.xyz \
  --output outputs/box.png \
  --shadow_mode soft
```

Debian/Ubuntu 常见系统依赖：

```bash
sudo apt-get install -y xvfb libgl1 libxrender1
```

## 文件结构

```text
pointcloud_renderer/
├── generate_demo_xyz.py
├── render_single.py
├── render_grid.py
├── render_multiview.py
├── render_benchmark.py
├── utils.py
├── shadow_utils.py
├── preview_utils.py
├── publication_utils.py
├── configs/colors.json
├── requirements.txt
└── README.md
```

运行 demo 后生成：

```text
demo_data/{box,cylinder,wedge,thin_plate,bracket}.xyz
outputs/*.png
```

## 调参建议

- 阴影过重：把 `--shadow_opacity` 降到 `0.07~0.09`。
- 阴影太散：把 `--shadow_blur` 降到 `20~26`。
- 点略偏大或偏小：优先使用 `--size_scale 0.85~1.15` 弱调节。
- 只有确需覆盖自动密度估计时才显式设置 `--sphere_radius`。
- 需要更强体积感：使用 `--light_preset studio`。
- 需要更多留白：增大 `--padding`，例如 `0.16`。
- 数万点渲染较慢：使用 `--mode fast --point_size 4~6`。
- 输入已归一化：单图使用 `--no-normalize`，网格使用 `--normalization none`。
