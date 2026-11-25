"""A placeholder for the scene model, used only to measure a training step.

It has the planned kind (a transformer encoder that emits every element in one
parallel pass), the planned output positions (32 bound, 16 structural) and
output fields of the planned shape, so that a timed step costs what a step of
the real model of that size would cost. Nothing else about it is real: its
inputs and targets are random numbers, its vocabulary sizes are guesses, and
its loss matches structural slots to targets by position, without the
minimum-cost assignment the real structure loss uses. It learns nothing and no
quality claim can be made from it.
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

BOUND_POSITIONS = 32
STRUCTURAL_POSITIONS = 16
# One token each for the viewport, the design condition and the visual preset.
CONDITIONING_POSITIONS = 3
SEQUENCE_LENGTH = CONDITIONING_POSITIONS + BOUND_POSITIONS + STRUCTURAL_POSITIONS

BOX_VALUES = 4
# Fill, text and border colour as RGB, then border width, corner radius,
# elevation, opacity, type size and type weight.
STYLE_VALUES = 15
NUMERIC_VALUES = BOX_VALUES + STYLE_VALUES
STRUCTURAL_TYPES = 4  # panel, divider, container, surface
PARENT_CHOICES = STRUCTURAL_POSITIONS + 1  # a structural slot, or the root

# Guessed input vocabulary. The adapter and generator (S1, S2) set the real one.
ROLES = 12
BINDING_KINDS = 8
STATES = 5  # default, hover, pressed, focused, disabled
DESIGN_FACTORS = 5
PRESET_TOKENS = 24


class PlaceholderSceneModel(nn.Module):
    def __init__(
        self,
        d_model: int,
        layers: int,
        heads: int,
        feedforward: int,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.identity = nn.Embedding(BOUND_POSITIONS, d_model)
        self.role = nn.Embedding(ROLES, d_model)
        self.binding = nn.Embedding(BINDING_KINDS, d_model)
        self.state = nn.Embedding(STATES, d_model)
        # Semantic relationship: the bound element this one belongs to, or none.
        self.belongs_to = nn.Embedding(BOUND_POSITIONS + 1, d_model)
        self.text = nn.Linear(2, d_model)  # text length and measured width
        self.viewport = nn.Linear(2, d_model)
        self.design_condition = nn.Linear(DESIGN_FACTORS, d_model)
        self.visual_preset = nn.Linear(PRESET_TOKENS, d_model)
        self.slots = nn.Parameter(torch.randn(STRUCTURAL_POSITIONS, d_model) * 0.02)

        layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=heads,
            dim_feedforward=feedforward,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d_model)

        self.bound_numeric = nn.Linear(d_model, NUMERIC_VALUES)
        self.bound_parent = nn.Linear(d_model, PARENT_CHOICES)
        self.slot_presence = nn.Linear(d_model, 1)
        self.slot_type = nn.Linear(d_model, STRUCTURAL_TYPES)
        self.slot_parent = nn.Linear(d_model, PARENT_CHOICES)
        self.slot_numeric = nn.Linear(d_model, NUMERIC_VALUES)

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        size = batch["role"].shape[0]
        positions = torch.arange(BOUND_POSITIONS, device=batch["role"].device)
        bound = (
            self.identity(positions)
            + self.role(batch["role"])
            + self.binding(batch["binding"])
            + self.state(batch["state"])
            + self.belongs_to(batch["belongs_to"])
            + self.text(batch["text"])
        )
        conditioning = torch.stack(
            [
                self.viewport(batch["viewport"]),
                self.design_condition(batch["design_condition"]),
                self.visual_preset(batch["visual_preset"]),
            ],
            dim=1,
        )
        slots = self.slots.unsqueeze(0).expand(size, -1, -1)
        tokens = torch.cat([conditioning, bound, slots], dim=1)

        # Only unused bound positions are padding.
        padding = torch.zeros(size, SEQUENCE_LENGTH, dtype=torch.bool, device=tokens.device)
        first = CONDITIONING_POSITIONS
        padding[:, first : first + BOUND_POSITIONS] = ~batch["bound_mask"]

        encoded = self.norm(self.encoder(tokens, src_key_padding_mask=padding))
        bound_out = encoded[:, first : first + BOUND_POSITIONS]
        slot_out = encoded[:, first + BOUND_POSITIONS :]
        return {
            "bound_numeric": self.bound_numeric(bound_out),
            "bound_parent": self.bound_parent(bound_out),
            "slot_presence": self.slot_presence(slot_out).squeeze(-1),
            "slot_type": self.slot_type(slot_out),
            "slot_parent": self.slot_parent(slot_out),
            "slot_numeric": self.slot_numeric(slot_out),
        }


def count_parameters(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)


def synthetic_batch(batch_size: int, generator: torch.Generator) -> dict[str, torch.Tensor]:
    """Random inputs and targets of the planned shapes, in 32-bit floats, on CPU."""

    def integers(high: int, *shape: int) -> torch.Tensor:
        return torch.randint(0, high, shape, generator=generator)

    def floats(*shape: int) -> torch.Tensor:
        return torch.rand(shape, generator=generator, dtype=torch.float32)

    bound_count = torch.randint(8, BOUND_POSITIONS + 1, (batch_size, 1), generator=generator)
    bound_mask = torch.arange(BOUND_POSITIONS).unsqueeze(0) < bound_count
    return {
        "role": integers(ROLES, batch_size, BOUND_POSITIONS),
        "binding": integers(BINDING_KINDS, batch_size, BOUND_POSITIONS),
        "state": integers(STATES, batch_size, BOUND_POSITIONS),
        "belongs_to": integers(BOUND_POSITIONS + 1, batch_size, BOUND_POSITIONS),
        "text": floats(batch_size, BOUND_POSITIONS, 2),
        "viewport": floats(batch_size, 2),
        "design_condition": floats(batch_size, DESIGN_FACTORS),
        "visual_preset": floats(batch_size, PRESET_TOKENS),
        "bound_mask": bound_mask,
        "target_bound_numeric": floats(batch_size, BOUND_POSITIONS, NUMERIC_VALUES),
        "target_bound_parent": integers(PARENT_CHOICES, batch_size, BOUND_POSITIONS),
        "target_slot_presence": (floats(batch_size, STRUCTURAL_POSITIONS) < 0.5).float(),
        "target_slot_type": integers(STRUCTURAL_TYPES, batch_size, STRUCTURAL_POSITIONS),
        "target_slot_parent": integers(PARENT_CHOICES, batch_size, STRUCTURAL_POSITIONS),
        "target_slot_numeric": floats(batch_size, STRUCTURAL_POSITIONS, NUMERIC_VALUES),
    }


def placeholder_structure_loss(
    output: dict[str, torch.Tensor], batch: dict[str, torch.Tensor]
) -> torch.Tensor:
    """Regression and classification terms of the planned kinds, padding masked.

    Structural slots are compared with targets by position. The real structure
    loss matches them by a minimum-cost assignment per example, which this
    placeholder does not run or time.
    """
    bound = batch["bound_mask"].float()
    present = batch["target_slot_presence"]

    def masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        return (values * mask).sum() / mask.sum().clamp(min=1.0)

    def classification(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        return F.cross_entropy(logits.flatten(0, 1), target.flatten(), reduction="none").view(
            target.shape
        )

    def regression(prediction: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        return (prediction - target).abs().mean(dim=-1)

    return (
        masked_mean(regression(output["bound_numeric"], batch["target_bound_numeric"]), bound)
        + masked_mean(classification(output["bound_parent"], batch["target_bound_parent"]), bound)
        + F.binary_cross_entropy_with_logits(output["slot_presence"], present)
        + masked_mean(classification(output["slot_type"], batch["target_slot_type"]), present)
        + masked_mean(classification(output["slot_parent"], batch["target_slot_parent"]), present)
        + masked_mean(regression(output["slot_numeric"], batch["target_slot_numeric"]), present)
    )
