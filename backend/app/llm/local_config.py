"""本地部署版的大模型配置：单用户、落盘在 data/local_llm.json。

网页版（多租户）的 BYOK 走数据库 + Fernet 加密；本地版没有数据库，也不需要做
多用户隔离，因此直接用一份明文 JSON 保存用户自己的 Key（本机文件系统，仅供本人使用）。
应用内「设置 → 我的大模型 API」读写这里；首次启动时若文件不存在，会用 .env 里的默认值播种，
这样「先在 .env 填好 Key 再启动」也能直接生效。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import get_settings


@dataclass
class LocalLLMConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""


_cfg: LocalLLMConfig | None = None


def _path() -> Path:
    return get_settings().data_dir / "local_llm.json"


def load_local_llm_config(force: bool = False) -> LocalLLMConfig:
    """读取本地配置；进程内缓存，save 后直接更新缓存，无需重启。"""
    global _cfg
    if _cfg is not None and not force:
        return _cfg
    path = _path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _cfg = LocalLLMConfig(
                base_url=str(data.get("base_url", "")),
                api_key=str(data.get("api_key", "")),
                model=str(data.get("model", "")),
            )
            return _cfg
        except Exception:  # noqa: BLE001 - 损坏时回退到 .env 默认值
            pass
    settings = get_settings()
    _cfg = LocalLLMConfig(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
    return _cfg


def save_local_llm_config(cfg: LocalLLMConfig) -> None:
    """原子写盘并刷新进程内缓存。"""
    global _cfg
    _cfg = cfg
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def mask_key(key: str) -> str:
    """只回显末 4 位，避免把完整 Key 下发到浏览器。"""
    if not key:
        return ""
    return "***" + key[-4:] if len(key) > 4 else "***"
