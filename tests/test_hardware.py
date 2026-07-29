"""unit tests for infrastructure.hardware.

covers the pure decision logic: tier classification, context/offload sizing, the
memory budget (which reserves headroom for other running apps), and rebuilding
the profile from the native THINKSTACK_HW_PROFILE env the tauri shell provides.
"""

import json


from infrastructure import hardware
from infrastructure.hardware import (
    HardwareProfile,
    _classify_tier,
    _profile_from_env,
    max_safe_model_size_gb,
    model_file_size_gb,
    profile_system,
    recommended_ctx_size,
    recommended_gpu_layers,
)


class TestClassifyTier:
    # ── use cases ──
    def test_low_end_machine(self):
        assert _classify_tier(total_ram_gb=8, vram_gb=0) == "low"

    def test_typical_laptop_is_medium(self):
        assert _classify_tier(total_ram_gb=16, vram_gb=0) == "medium"

    def test_workstation_is_high(self):
        assert _classify_tier(total_ram_gb=32, vram_gb=12) == "high"

    def test_gpu_alone_lifts_tier(self):
        # plenty of vram but little ram still counts as at least medium/high
        assert _classify_tier(total_ram_gb=8, vram_gb=10) == "high"

    # ── boundary / edge cases ──
    def test_ram_boundary_12_is_medium_not_low(self):
        assert _classify_tier(total_ram_gb=12, vram_gb=0) == "medium"

    def test_ram_boundary_24_is_medium_not_high(self):
        # threshold is strict (> 24), so exactly 24 stays medium
        assert _classify_tier(total_ram_gb=24, vram_gb=0) == "medium"

    def test_vram_boundary_2_is_medium(self):
        assert _classify_tier(total_ram_gb=4, vram_gb=2) == "medium"

    def test_vram_boundary_8_is_medium_not_high(self):
        assert _classify_tier(total_ram_gb=4, vram_gb=8) == "medium"

    def test_zero_everything_is_low(self):
        assert _classify_tier(total_ram_gb=0, vram_gb=0) == "low"


class TestRecommendedCtxSize:
    def test_known_tiers(self):
        assert recommended_ctx_size("low") == 2048
        assert recommended_ctx_size("medium") == 4096
        assert recommended_ctx_size("high") == 8192

    def test_unknown_tier_falls_back_to_smallest(self):
        # graceful: an unexpected tier string must not KeyError
        assert recommended_ctx_size("bogus") == 2048


class TestRecommendedGpuLayers:
    def test_insufficient_vram_is_cpu_only(self):
        assert recommended_gpu_layers(vram_gb=1.0, model_size_gb=1.0) == 0

    def test_vram_just_below_threshold(self):
        assert recommended_gpu_layers(vram_gb=1.49, model_size_gb=0.1) == 0

    def test_model_fits_gets_full_offload(self):
        # 8gb vram, 0.5gb headroom -> 7.5gb usable, a 1gb model fits entirely
        assert recommended_gpu_layers(vram_gb=8.0, model_size_gb=1.0) == -1

    def test_partial_offload_is_fraction_of_layers(self):
        # 4gb vram -> 3.5 usable; a 7gb model -> fraction 0.5 -> 16 of 32 layers
        assert recommended_gpu_layers(vram_gb=4.0, model_size_gb=7.0) == 16

    def test_partial_offload_never_exceeds_32(self):
        layers = recommended_gpu_layers(vram_gb=100.0, model_size_gb=0.001)
        assert layers == -1  # trivially fits -> full offload sentinel

    def test_partial_offload_never_negative(self):
        assert recommended_gpu_layers(vram_gb=1.6, model_size_gb=1000.0) >= 0


class TestMaxSafeModelSize:
    def test_reserves_headroom_for_other_apps(self):
        # 16gb free, reserve 3gb, no vram -> 13gb budget
        assert max_safe_model_size_gb(available_ram_gb=16.0, vram_gb=0.0) == 13.0

    def test_vram_adds_to_budget(self):
        assert max_safe_model_size_gb(available_ram_gb=8.0, vram_gb=4.0) == 9.0

    def test_never_negative_on_constrained_machine(self):
        # less free ram than the reserve -> budget floors at the vram only
        assert max_safe_model_size_gb(available_ram_gb=1.0, vram_gb=0.0) == 0.0

    def test_constrained_machine_still_counts_vram(self):
        assert max_safe_model_size_gb(available_ram_gb=1.0, vram_gb=2.0) == 2.0


class TestModelFileSize:
    def test_reports_size_in_gb(self, tmp_path):
        p = tmp_path / "model.gguf"
        with open(p, "wb") as f:
            f.truncate(2 * 1024 ** 3)  # exactly 2 GiB
        assert model_file_size_gb(p) == 2.0

    def test_missing_file_is_zero_not_error(self, tmp_path):
        assert model_file_size_gb(tmp_path / "nope.gguf") == 0.0


class TestProfileFromEnv:
    def test_absent_env_returns_none(self, monkeypatch):
        monkeypatch.delenv("THINKSTACK_HW_PROFILE", raising=False)
        assert _profile_from_env() is None

    def test_parses_full_profile(self, monkeypatch):
        payload = {
            "total_ram_gb": 15.0, "available_ram_gb": 4.9, "cpu_cores": 8,
            "gpu_name": "NVIDIA RTX 3050 Ti", "vram_gb": 4.0, "has_cuda": True,
            "tier": "medium",
        }
        monkeypatch.setenv("THINKSTACK_HW_PROFILE", json.dumps(payload))
        p = _profile_from_env()
        assert isinstance(p, HardwareProfile)
        assert p.total_ram_gb == 15.0 and p.available_ram_gb == 4.9
        assert p.cpu_cores == 8 and p.has_cuda is True
        assert p.gpu_name == "NVIDIA RTX 3050 Ti" and p.tier == "medium"

    def test_missing_tier_is_recomputed(self, monkeypatch):
        monkeypatch.setenv(
            "THINKSTACK_HW_PROFILE",
            json.dumps({"total_ram_gb": 16.0, "vram_gb": 0.0}),
        )
        p = _profile_from_env()
        assert p.tier == "medium"  # derived via _classify_tier

    def test_cpu_threads_fallback_key(self, monkeypatch):
        # rust emits both cpu_cores and cpu_threads; tolerate only cpu_threads
        monkeypatch.setenv(
            "THINKSTACK_HW_PROFILE",
            json.dumps({"total_ram_gb": 8.0, "cpu_threads": 4}),
        )
        assert _profile_from_env().cpu_cores == 4

    def test_malformed_json_returns_none(self, monkeypatch):
        monkeypatch.setenv("THINKSTACK_HW_PROFILE", "{not valid json")
        assert _profile_from_env() is None

    def test_wrong_types_return_none(self, monkeypatch):
        monkeypatch.setenv(
            "THINKSTACK_HW_PROFILE",
            json.dumps({"total_ram_gb": "sixteen"}),
        )
        assert _profile_from_env() is None


class TestProfileSystemPrefersEnv:
    def test_uses_env_profile_without_detecting(self, monkeypatch):
        monkeypatch.setattr(hardware, "_cached_profile", None)
        monkeypatch.setenv(
            "THINKSTACK_HW_PROFILE",
            json.dumps({"total_ram_gb": 64.0, "vram_gb": 24.0, "tier": "high"}),
        )
        # if it detected locally instead, tier/ram would reflect this machine.
        # guard against that by making local detection blow up if reached.
        monkeypatch.setattr(
            hardware, "_detect_ram",
            lambda: (_ for _ in ()).throw(AssertionError("should not detect")),
        )
        p = profile_system()
        assert p.tier == "high" and p.total_ram_gb == 64.0

    def test_result_is_cached(self, monkeypatch):
        monkeypatch.setattr(hardware, "_cached_profile", None)
        monkeypatch.setenv(
            "THINKSTACK_HW_PROFILE",
            json.dumps({"total_ram_gb": 16.0, "vram_gb": 0.0}),
        )
        first = profile_system()
        # change the env; a cached call must ignore it
        monkeypatch.setenv(
            "THINKSTACK_HW_PROFILE",
            json.dumps({"total_ram_gb": 999.0, "vram_gb": 0.0}),
        )
        assert profile_system() is first
