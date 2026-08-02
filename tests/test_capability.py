"""What this machine can do, asserted against machines nobody here owns.

Every profile below is fabricated, which is the point: policy that only works
on the developer's laptop is how an 8 GB M1 ended up unable to summarize. These
run on any OS with no GPU and no model files.

Written to break it, not to confirm it: zero-memory machines, unknown tiers,
models larger than the whole system, and engines that lie about what they can
do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.capability import (
    OUTPUT_CEILING,
    OUTPUT_FLOOR,
    TYPICAL_PAPER_CHARS,
    MachineCapability,
)
from infrastructure.hardware import HardwareProfile


def machine(**kw) -> HardwareProfile:
    """A profile with sane defaults; override only what a test cares about."""
    base = dict(total_ram_gb=16.0, available_ram_gb=8.0, cpu_cores=8, tier="medium")
    base.update(kw)
    return HardwareProfile(**base)


M1_8GB = machine(total_ram_gb=8, available_ram_gb=4, gpu_name="Apple Silicon",
                 gpu_vendor="apple", unified_memory=True, tier="low")
RTX = machine(total_ram_gb=32, available_ram_gb=20, gpu_name="RTX 4070",
              gpu_vendor="nvidia", vram_gb=12, has_cuda=True, tier="high")


class TestTheEngineDecidesOffloadNotTheHardware:
    """The bug this module exists to kill.

    GPU layers used to be `has_cuda && vram_gb >= 2.0`. Apple Silicon reports
    no CUDA and 0 GB dedicated VRAM -- both true -- so every Mac ran on the CPU
    regardless of whether its engine supported Metal.
    """

    def test_apple_silicon_offloads_when_the_engine_can(self):
        assert MachineCapability(M1_8GB, engine_offload=True).gpu_layers(1.0) == -1

    def test_apple_silicon_does_not_when_the_engine_cannot(self):
        assert MachineCapability(M1_8GB, engine_offload=False).gpu_layers(1.0) == 0

    def test_a_cuda_card_is_ignored_if_the_wheel_is_cpu_only(self):
        # A CPU-only build cannot offload no matter what is plugged in, and
        # claiming otherwise raises at model load rather than degrading.
        assert MachineCapability(RTX, engine_offload=False).gpu_layers(1.0) == 0

    def test_a_cuda_card_is_used_when_the_wheel_supports_it(self):
        assert MachineCapability(RTX, engine_offload=True).gpu_layers(1.0) == -1

    def test_zero_vram_discrete_gpu_stays_on_cpu(self):
        # Not unified memory, and no VRAM to speak of: nothing to offload into.
        p = machine(gpu_vendor="nvidia", vram_gb=0.0, unified_memory=False)
        assert MachineCapability(p, engine_offload=True).gpu_layers(1.0) == 0


class TestTheWindowHoldsBothPromptAndReply:
    """The arithmetic nobody owned.

    6000 chars of paper (~1500 tokens) plus 1024 tokens of reply is ~2650
    tokens, inside a 2048-token window. It could not fit, and the failure was
    reported to the reader as an unreadable model response.
    """

    @pytest.mark.parametrize("tier,ctx", [("low", 2048), ("medium", 4096), ("high", 8192)])
    def test_context_follows_the_tier(self, tier, ctx):
        assert MachineCapability(machine(tier=tier)).context_size() == ctx

    @pytest.mark.parametrize("tier", ["low", "medium", "high"])
    def test_prompt_and_reply_always_fit_the_window(self, tier):
        c = MachineCapability(machine(tier=tier))
        ctx = c.context_size()
        out = c.output_tokens(ctx)
        prompt_tokens = c.input_chars(ctx, out) / 4
        assert prompt_tokens + out <= ctx, "the request cannot exceed its own context"

    def test_output_is_clamped_at_both_ends(self):
        assert MachineCapability(machine(tier="low")).output_tokens() >= OUTPUT_FLOOR
        assert MachineCapability(machine(tier="high")).output_tokens() <= OUTPUT_CEILING

    def test_a_small_window_is_not_half_eaten_by_the_reply(self):
        # Found by mutation: pinning output at 1024 kept every other test
        # green, because input_chars simply shrank to compensate. It is safe
        # but wasteful -- on a 2048 window it leaves 3481 characters for the
        # paper instead of 5222. The reply must scale with the window, not
        # just fit inside it.
        c = MachineCapability(machine(tier="low"))
        ctx = c.context_size()
        assert c.output_tokens(ctx) < ctx // 3, "the reply must not dominate a small window"

    def test_the_reply_budget_grows_with_the_window(self):
        small = MachineCapability(machine(tier="low")).output_tokens()
        large = MachineCapability(machine(tier="high")).output_tokens()
        assert large > small

    def test_a_bigger_machine_gets_more_room_for_the_paper(self):
        small = MachineCapability(machine(tier="low")).input_chars()
        large = MachineCapability(machine(tier="high")).input_chars()
        assert large > small

    def test_an_unknown_tier_falls_back_to_the_smallest_window(self):
        # A future Rust build could send a tier this Python does not know.
        # Guessing large would overflow the context; guessing small only costs
        # speed.
        assert MachineCapability(machine(tier="quantum")).context_size() == 2048

    def test_an_empty_tier_does_not_crash(self):
        assert MachineCapability(machine(tier="")).context_size() == 2048


class TestWhetherAModelFitsAtAll:
    def test_a_model_larger_than_free_memory_does_not_fit(self):
        p = machine(total_ram_gb=8, available_ram_gb=1.2)
        plan = MachineCapability(p).plan_for_size(4.0)
        assert plan.fits is False
        assert "GB" in plan.reason, "the reason must be sayable to a user"

    def test_a_small_model_fits_a_modest_machine(self):
        assert MachineCapability(M1_8GB).can_run(0.5) is True

    def test_unknown_memory_does_not_block_the_user(self):
        # available_ram_gb == 0 means "we could not measure", not "no memory".
        # Refusing on an unknown would brick the app on a machine we simply
        # failed to profile.
        p = machine(total_ram_gb=0.0, available_ram_gb=0.0)
        assert MachineCapability(p).can_run(4.0) is True

    def test_an_absurd_model_is_refused(self):
        assert MachineCapability(RTX).can_run(500.0) is False

    def test_a_missing_file_is_refused_without_raising(self):
        plan = MachineCapability(RTX).plan_for_file(Path("/does/not/exist.gguf"))
        assert plan.fits is False
        assert "exist.gguf" in plan.reason


class TestMapReduceIsDecidedByRoomNotGuesswork:
    def test_a_cramped_machine_needs_multiple_passes(self):
        c = MachineCapability(machine(tier="low"))
        assert c.plan_for_size(0.5).needs_map_reduce is True
        assert c.input_chars() < TYPICAL_PAPER_CHARS

    def test_a_roomy_machine_reads_a_paper_in_one_pass(self):
        c = MachineCapability(machine(tier="high"))
        assert c.plan_for_size(0.5).needs_map_reduce is False


class TestUnifiedMemoryIsNotZeroMemory:
    def test_apple_silicon_gpu_memory_comes_from_system_ram(self):
        c = MachineCapability(M1_8GB, engine_offload=True)
        assert c.usable_gpu_memory_gb > 0, "0 GB VRAM does not mean no GPU"
        assert c.usable_gpu_memory_gb <= M1_8GB.total_ram_gb

    def test_no_gpu_memory_is_claimed_when_the_engine_cannot_offload(self):
        assert MachineCapability(M1_8GB, engine_offload=False).usable_gpu_memory_gb == 0.0

    def test_a_discrete_card_reports_its_own_vram(self):
        assert MachineCapability(RTX, engine_offload=True).usable_gpu_memory_gb == 12.0


class TestTheReportTheUIRenders:
    def test_report_is_data_not_prose(self):
        r = MachineCapability(M1_8GB, engine_offload=False).report()
        assert set(r) == {"machine", "engine", "limits", "advice"}
        assert isinstance(r["advice"], list)
        assert isinstance(r["limits"]["context_size"], int)

    def test_a_mac_with_an_unusable_gpu_is_told_so(self):
        advice = " ".join(MachineCapability(M1_8GB, engine_offload=False).advice())
        assert "Metal" in advice

    def test_a_cuda_card_with_a_cpu_wheel_is_told_so(self):
        advice = " ".join(MachineCapability(RTX, engine_offload=False).advice())
        assert "RTX 4070" in advice

    def test_advice_is_never_empty(self):
        # An empty list renders as a blank panel, which reads as a broken app.
        for p in (M1_8GB, RTX, machine(), machine(total_ram_gb=0)):
            for off in (True, False):
                assert MachineCapability(p, off).advice()

    def test_low_memory_is_mentioned(self):
        p = machine(available_ram_gb=1.0)
        assert any("free" in a for a in MachineCapability(p).advice())


class TestItNeverCrashesOnNonsense:
    """Detection can fail or a future Rust build can send something new. None
    of that may take the app down: a wrong number is recoverable, an exception
    during startup is not."""

    @pytest.mark.parametrize("p", [
        HardwareProfile(),                                   # everything default
        machine(total_ram_gb=-5, available_ram_gb=-1),       # nonsense values
        machine(cpu_cores=0),
        machine(gpu_vendor="unknown-vendor", vram_gb=-2),
        machine(unified_memory=True, total_ram_gb=0),
    ])
    def test_a_full_plan_is_still_produced(self, p):
        for off in (True, False):
            plan = MachineCapability(p, off).plan_for_size(1.0)
            assert plan.n_ctx > 0
            assert plan.output_tokens >= OUTPUT_FLOOR
            assert plan.input_chars >= 0
            assert plan.n_gpu_layers >= -1
            MachineCapability(p, off).report()   # must not raise

    def test_a_zero_size_model_is_handled(self):
        assert MachineCapability(RTX, True).plan_for_size(0.0).fits is True

    def test_a_negative_size_model_does_not_produce_nonsense_layers(self):
        assert MachineCapability(RTX, True).gpu_layers(-1.0) in (-1, 0)
