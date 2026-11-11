"""冷存：verbatim 原文存储（阶段3 双痕迹的冷库）。"""
from __future__ import annotations

import hashlib
import os
from typing import Protocol


class BlobStore(Protocol):
    def put(self, data: bytes) -> str: ...
    def get(self, ref: str) -> bytes: ...
    def delete(self, ref: str) -> bool: ...


class InMemoryBlobStore:
    """内存冷存（测试/演示）。"""

    def __init__(self) -> None:
        self._d: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        ref = "mem:" + hashlib.sha256(data).hexdigest()[:32]
        self._d[ref] = data
        return ref

    def get(self, ref: str) -> bytes:
        return self._d[ref]

    def delete(self, ref: str) -> bool:
        return self._d.pop(ref, None) is not None


class LocalFileBlobStore:
    """本地文件冷存（生产单机）。按内容哈希分片存放。"""

    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def put(self, data: bytes) -> str:
        h = hashlib.sha256(data).hexdigest()
        sub = os.path.join(self.root, h[:2])
        os.makedirs(sub, exist_ok=True)
        path = os.path.join(sub, h)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(data)
        return "file:" + h

    def get(self, ref: str) -> bytes:
        h = ref.split(":", 1)[1]
        with open(os.path.join(self.root, h[:2], h), "rb") as f:
            return f.read()

    def delete(self, ref: str) -> bool:
        """删除一个 blob（仅用于确认无人再引用后清理）。返回是否真的删了。"""
        h = ref.split(":", 1)[1]
        path = os.path.join(self.root, h[:2], h)
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False
