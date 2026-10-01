"""Vision Transformer matching the FSFM / FS-VFM fine-tuned checkpoints.

Upstream builds on ``timm==0.4.5``'s VisionTransformer with global average pooling
(``fc_norm`` instead of the final ``norm``). This is a dependency-free re-implementation
with the same parameter names, so the checkpoints load with ``strict=True``: a missing
or unexpected key is an error rather than a silently random layer.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass(frozen=True)
class ViTArch:
    embed_dim: int
    depth: int
    num_heads: int
    patch_size: int = 16
    img_size: int = 224
    mlp_ratio: float = 4.0


ARCHS = {
    "vit_small_patch16": ViTArch(384, 12, 12),   # MoCo-v3 ViT-S, as used by FS-VFM
    "vit_base_patch16": ViTArch(768, 12, 12),
    "vit_large_patch16": ViTArch(1024, 24, 16),
}


class PatchEmbed(nn.Module):
    def __init__(self, a: ViTArch):
        super().__init__()
        self.proj = nn.Conv2d(3, a.embed_dim, kernel_size=a.patch_size, stride=a.patch_size)

    def forward(self, x):
        return self.proj(x).flatten(2).transpose(1, 2)


class Attention(nn.Module):
    def __init__(self, dim: int, num_heads: int):
        super().__init__()
        self.num_heads = num_heads
        self.qkv = nn.Linear(dim, dim * 3, bias=True)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x):
        b, n, c = x.shape
        q, k, v = self.qkv(x).reshape(b, n, 3, self.num_heads, c // self.num_heads).permute(2, 0, 3, 1, 4)
        x = F.scaled_dot_product_attention(q, k, v)
        return self.proj(x.transpose(1, 2).reshape(b, n, c))


class Mlp(nn.Module):
    def __init__(self, dim: int, hidden: int):
        super().__init__()
        self.fc1 = nn.Linear(dim, hidden)
        self.fc2 = nn.Linear(hidden, dim)

    def forward(self, x):
        return self.fc2(F.gelu(self.fc1(x)))


class Block(nn.Module):
    def __init__(self, dim: int, num_heads: int, mlp_ratio: float):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim, eps=1e-6)
        self.attn = Attention(dim, num_heads)
        self.norm2 = nn.LayerNorm(dim, eps=1e-6)
        self.mlp = Mlp(dim, int(dim * mlp_ratio))

    def forward(self, x):
        x = x + self.attn(self.norm1(x))
        return x + self.mlp(self.norm2(x))


class VisionTransformer(nn.Module):
    """ViT with global average pooling over patch tokens (FSFM fine-tuning setup)."""

    def __init__(self, arch: ViTArch, num_classes: int):
        super().__init__()
        self.arch = arch
        n_patches = (arch.img_size // arch.patch_size) ** 2
        self.patch_embed = PatchEmbed(arch)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, arch.embed_dim))
        self.pos_embed = nn.Parameter(torch.zeros(1, n_patches + 1, arch.embed_dim))
        self.blocks = nn.ModuleList(Block(arch.embed_dim, arch.num_heads, arch.mlp_ratio) for _ in range(arch.depth))
        self.fc_norm = nn.LayerNorm(arch.embed_dim, eps=1e-6)
        self.head = nn.Linear(arch.embed_dim, num_classes)

    def tokens(self, x):
        x = self.patch_embed(x)
        x = torch.cat((self.cls_token.expand(x.shape[0], -1, -1), x), dim=1) + self.pos_embed
        for blk in self.blocks:
            x = blk(x)
        return x

    def forward_features(self, x):
        """Pooled, normalised embedding (B, embed_dim)."""
        return self.fc_norm(self.tokens(x)[:, 1:, :].mean(dim=1))

    def forward(self, x):
        return self.head(self.forward_features(x))


def build_vit(arch_name: str, num_classes: int) -> VisionTransformer:
    try:
        arch = ARCHS[arch_name]
    except KeyError:
        raise ValueError(f"unknown architecture {arch_name!r}; expected one of {sorted(ARCHS)}") from None
    return VisionTransformer(arch, num_classes)
