# MoFox Period Plugin - 重构版

## 项目结构

插件已重构为模块化设计，代码结构更加清晰，易于维护。

```
mofox_period_plugin/
├── __init__.py              # 包初始化文件
├── plugin.py                # 插件主类（简洁版，只包含配置和注册）
│
├── models/                  # 数据模型层
│   ├── __init__.py
│   └── cycle_models.py      # 周期数据模型（CyclePhase, DualCycleData）
│
├── managers/                # 业务逻辑层
│   ├── __init__.py
│   ├── cycle_manager.py     # 双周期锚定管理器
│   └── state_manager.py     # 周期状态管理器
│
├── utils/                   # 工具类层
│   ├── __init__.py
│   └── prompt_templates.py  # 提示词模板系统
│
└── components/              # 组件层
    ├── __init__.py
    ├── prompts.py          # Prompt组件
    ├── commands.py         # Command组件
    └── event_handlers.py   # EventHandler组件
```

## 模块说明

### 1. models/ - 数据模型层
定义插件使用的所有数据结构，职责单一，不包含业务逻辑。

- **CyclePhase**: 周期阶段定义（月经期、卵泡期、排卵期、黄体期）
- **DualCycleData**: 双周期数据模型，包含序列化/反序列化方法

### 2. managers/ - 业务逻辑层
包含核心业务逻辑，与组件层解耦。

- **DualCycleManager**: 
  - 负责生成和管理双周期数据
  - 计算当前所处的周期阶段
  - 处理周期的存储和恢复
  
- **PeriodStateManager**:
  - 基于DualCycleManager计算当前状态
  - 管理状态缓存
  - 生成痛经等级

### 3. utils/ - 工具类层
提供各种辅助功能。

- **PromptTemplates**: 
  - 提供10级生理影响提示词
  - 提供10级心理影响提示词
  - 提供11级痛经提示词（0-10）

### 4. components/ - 组件层
实现插件系统的各种组件，调用managers层的业务逻辑。

- **PeriodStatePrompt**: 生成并注入周期状态提示词到AI对话中
- **PeriodStatusCommand**: `/period` 命令，查询当前状态
- **RegenerateCycleCommand**: `/regenerate_cycle` 命令，重新生成周期
- **PeriodStateUpdateHandler**: 处理插件启动事件，初始化管理器

### 5. plugin.py - 插件主类
简洁的插件入口，只包含：
- 插件元数据定义
- 配置Schema定义
- 组件注册逻辑

## 优势

### ✅ 模块化设计
每个模块职责单一，易于理解和修改。

### ✅ 易于维护
- 需要修改数据结构？只改 `models/`
- 需要修改业务逻辑？只改 `managers/`
- 需要修改提示词？只改 `utils/prompt_templates.py`
- 需要添加新命令？只改 `components/commands.py`

### ✅ 可测试性
每个模块都可以独立测试，无需依赖整个插件系统。

### ✅ 可扩展性
- 添加新的周期模型？在 `models/` 中创建新文件
- 添加新的管理器？在 `managers/` 中创建新文件
- 添加新的工具类？在 `utils/` 中创建新文件
- 添加新的组件？在 `components/` 中创建新文件

### ✅ 符合最佳实践
- 遵循单一职责原则
- 遵循依赖倒置原则
- 遵循开闭原则
- 清晰的分层架构

## 使用方法

插件的使用方法与之前完全相同，只是代码组织更加清晰：

```python
# 用户命令
/period              # 查询当前周期状态
/regenerate_cycle    # 重新生成双周期数据
```

## 配置文件

配置文件结构保持不变，位于 `config.toml`：

```toml
[plugin]
enabled = true
config_version = "3.0.0"
debug_mode = false

[cycle]
anchor_day = 15  # 每月锚点日期

[levels]
menstrual_physical = 5
menstrual_psychological = 4
follicular_physical = 2
follicular_psychological = 2
ovulation_physical = 3
ovulation_psychological = 2
luteal_physical = 4
luteal_psychological = 3
```

## 开发指南

### 添加新功能

1. **添加新的数据模型**
   - 在 `models/` 中创建新文件
   - 在 `models/__init__.py` 中导出

2. **添加新的业务逻辑**
   - 在 `managers/` 中创建新管理器
   - 在 `managers/__init__.py` 中导出

3. **添加新的命令**
   - 在 `components/commands.py` 中添加新的Command类
   - 在 `plugin.py` 的 `get_plugin_components()` 中注册

4. **修改提示词**
   - 直接编辑 `utils/prompt_templates.py`

### 调试技巧

启用调试模式：
```toml
[plugin]
debug_mode = true
```

这将在日志中输出详细的状态信息。

## 迁移说明

如果您之前使用的是旧版本（单文件版本），数据会自动兼容：
- 存储格式完全相同
- 配置文件完全兼容
- 功能行为完全一致

只是代码组织方式改变了，更易于维护和扩展。

## 备份文件

重构时已自动创建备份文件：
- `plugin.py.backup` - 旧版本的完整代码

如需恢复旧版本，只需删除新文件并重命名备份文件即可。
