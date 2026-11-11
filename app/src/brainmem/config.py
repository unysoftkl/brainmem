"""配置加载与校验（Pydantic Settings）。参数总表外置，代码无魔法数字。"""
from __future__ import annotations

import os
from typing import Any

import yaml
from pydantic import BaseModel, Field

from brainmem.core.params import WeightParams


class WeightConfig(BaseModel):
    k: float = Field(0.016, gt=0)
    H: float = Field(3.0, ge=0)
    C: float = Field(0.10, gt=0)
    S0: float = Field(8.0, gt=0)
    W_MAX: float = Field(20.0, gt=0)
    G0: float = Field(2.0, ge=0)
    beta: float = Field(1.20, ge=0)
    gamma: float = Field(0.80, ge=0)
    S_MAX: int = Field(24, ge=1)
    k_e: float = Field(0.004, gt=0)
    H_e: float = Field(1.5, ge=0)
    C_e: float = Field(0.10, gt=0)
    E_MAX: float = Field(10.0, gt=0)
    g_e: float = Field(1.20, ge=0)
    merge_edge: float = Field(8.0, gt=0)
    merge_coact: int = Field(5, ge=0)

    def to_params(self) -> WeightParams:
        return WeightParams(**self.model_dump())


class Config(BaseModel):
    tenant: str = "default"
    dedup_window_minutes: float = 5.0
    storage: str = "sqlite"
    sqlite_path: str = "brainmem.db"
    # 语义查重（双门限）默认关闭：热写路径只做精确同名去重，保证 P95 < 5ms。
    # 小规模集合（数百节点）或需要近义合并时开启；大规模应走 ANN 索引（阶段6）。
    semantic_dedup: bool = False
    weights: WeightConfig = Field(default_factory=WeightConfig)

    def params(self) -> WeightParams:
        return self.weights.to_params()

    @property
    def dedup_window_days(self) -> float:
        return self.dedup_window_minutes / 1440.0


def load_config(path: str | None = None) -> Config:
    """从 YAML/JSON 加载；path 为空则回退到环境变量 BRAINMEM_CONFIG，再回退内置默认。"""
    if not path:
        path = os.environ.get("BRAINMEM_CONFIG")
    data: dict[str, Any] = {}
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    cfg = Config(**data)
    preset = os.environ.get("BRAINMEM_PRESET")
    if preset and preset in ("fast", "long", "ultra"):
        kmap = {"fast": 0.016, "long": 0.008, "ultra": 0.004}
        cfg.weights.k = kmap[preset]
    # 环境变量覆盖库路径（桌面试用环境用同一份 db）
    db_env = os.environ.get("BRAINMEM_DB")
    if db_env:
        cfg.sqlite_path = db_env
    # 展开 ${VAR} / %VAR% / ~ （支持 config.json 里写 %LOCALAPPDATA% 之类的路径）
    if cfg.sqlite_path:
        cfg.sqlite_path = os.path.expandvars(os.path.expanduser(cfg.sqlite_path))
    return cfg
