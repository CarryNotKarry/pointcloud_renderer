# 上传到 GitHub 的中文说明

## 推荐：两个工具上传到同一个仓库

命令行版和交互工作台共享代码，已经在同一个本地仓库里，上传一次就能保留两者。

### 一、创建空仓库

登录 GitHub，创建新仓库，例如 `pointcloud-renderer`。公开或私有由你选择。不要勾选自动创建说明文件、忽略文件或许可证，避免与本地历史冲突。

### 二、提交新增的中文文档

```bash
cd /Users/carry/test/HGS-PU_new/pointcloud_renderer
git status
git add README.md CLI_GUIDE.md GITHUB_UPLOAD.md
git commit -m "补充中文说明和上传指南"
```

若提示缺少作者身份，填入自己的信息后重新提交；以下设置只影响当前仓库：

```bash
git config user.name "你的名字"
git config user.email "你的邮箱"
```

### 三、连接并上传

替换下面的用户名和仓库名：

```bash
git remote add origin https://github.com/你的用户名/pointcloud-renderer.git
git push -u origin main
git push origin --tags
```

当前目录已经是 Git 仓库，不需要重新初始化。编写本文时还没有配置远程地址，也没有替你上传。

如果提示远程地址已经存在，先执行 `git remote -v` 检查。只有确认原地址不需要保留时，才用 `git remote set-url origin 新地址` 修改。不要为解决上传错误而强制推送。

按凭据管理器或终端提示完成认证；不要把令牌或密码写入代码、远程地址或聊天消息。

上传后主分支包含两个工具。`cli-v1`、`workbench-v1`、`workbench-v2` 标签保留对应的历史版本，旧标签不会包含本次新增的中文首页。

流程参考 [GitHub 官方上传说明](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)。

## 可选：分成两个仓库上传

创建两个空仓库，例如 `pointcloud-renderer-cli` 和 `pointcloud-renderer-workbench`。

本项目的 `releases/` 中已有两个源码包：

- `pointcloud-renderer-cli-v1.zip`：原命令行版。
- `pointcloud-renderer-workbench-v2.zip`：增强工作台，保留其依赖的命令行渲染模块。

分别解压到两个不同的新文件夹，不要覆盖现有项目。压缩包是历史快照，不含 Git 历史和本次新增文档。交互版可以额外复制当前的 `README.md`、`CLI_GUIDE.md` 和 `GITHUB_UPLOAD.md`；命令行版保留包内原说明即可。

先进入命令行版解压后的源码目录（能看到 `requirements.txt` 的目录），执行：

```bash
git init
git add .
git commit -m "初始化命令行渲染工具"
git branch -M main
git remote add origin https://github.com/你的用户名/pointcloud-renderer-cli.git
git push -u origin main
```

再进入交互版解压后的源码目录，执行：

```bash
git init
git add .
git commit -m "初始化交互渲染工作台"
git branch -M main
git remote add origin https://github.com/你的用户名/pointcloud-renderer-workbench.git
git push -u origin main
```

若缺少作者身份，按前面的方式在各仓库配置。应上传解压后的源代码，不是只上传压缩包。分开后两份代码需要分别维护。

## 上传前检查

- 只在 `pointcloud_renderer` 目录操作，不要把整个研究项目上传。
- 当前忽略规则排除了 `.venv/`、`outputs/`、`workbench_data/` 和压缩包；额外添加的数据目录需要自行检查。
- 提交前用 `git status` 检查文件，不要上传未公开数据、密钥或包含私人路径的会话。
- 源码包可以放在 GitHub 的发行版本附件里，不必强行加入源代码目录。
- 如需开源授权，请自行选择合适的许可证。

以后更新时，检查改动、提交需要的文件，再执行 `git push` 即可。
