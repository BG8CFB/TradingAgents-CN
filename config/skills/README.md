# 用户 Skill 目录

本目录是**用户级 skill 根目录**（可写，优先级最高，可覆盖内置同名 skill）。

放置格式：`{skill-name}/SKILL.md`（frontmatter 必填 `description`；可选 `manifest.yaml` + `scripts/` 声明可执行入口）。也可通过 Web UI「系统配置 → 技能管理」从 Git URL 安装。

- 内置只读 skill 目录：`app/engine/tools/skill/builtin/`（随代码发布，当前为空）
- 架构说明：`docs/skill-architecture.md`

注：项目早期预置的方法论 skill（risk-aware-analysis / sector-rotation / technical-screening）已移除；数值/金额计算统一改由内置计算工具（`calc_expression` 等 builtin tool）确定性完成。
