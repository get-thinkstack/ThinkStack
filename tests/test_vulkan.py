"""what graphics hardware we decide is worth using.

None of these tests may need a GPU, a driver, or a Vulkan loader: they run on CI
machines that have none of the three, which is also the state of a great many
user machines. Devices are therefore injected rather than detected.

The cases that matter are the ones that would be wrong in a way nobody notices:

  * **llvmpipe** is a software rasteriser -- the processor pretending to be a
    graphics card. Offloading to it means routing work through a translation
    layer to reach the CPU that was already doing it, while every check reports
    success. It is the only device here that is dangerous rather than merely
    unhelpful.
  * **Reported memory is not video memory.** On the laptop this was developed
    on, an Intel iGPU and an RTX 3050 Ti both claim 12.4 GB, which is system
    RAM; the card has 4 GB. So nothing may decide usability from heap size.
"""

from __future__ import annotations

import pytest

from infrastructure import vulkan
from infrastructure.vulkan import VulkanDevice

GB = 1_000_000_000


def dev(name="Test GPU", vendor="Intel", kind="integrated", heap=4 * GB, api="1.3"):
    return VulkanDevice(name=name, vendor=vendor, kind=kind,
                        heap_bytes=heap, api_version=api)


# the three devices actually reported by the development laptop
INTEL_IGPU = dev("Intel(R) UHD Graphics (TGL GT1)", "Intel", "integrated", 12_400_000_000)
NVK_3050 = dev("NVIDIA GeForce RTX 3050 Ti Laptop GPU (NVK GA107)", "NVIDIA",
               "discrete", 12_400_000_000)
LLVMPIPE = dev("llvmpipe (LLVM 22.1.8, 256 bits)", "0x10005", "software", 16_500_000_000)


@pytest.fixture
def devices(monkeypatch):
    """inject a device list. Returns a setter."""
    def setter(items):
        monkeypatch.setattr(vulkan, "enumerate_devices", lambda: list(items))
        monkeypatch.setattr(vulkan, "available", lambda: bool(items))
    return setter


class TestWhichDevicesAreWorthUsing:
    def test_a_discrete_card_is(self):
        assert dev(kind="discrete").usable

    def test_an_integrated_gpu_is(self):
        # a weak iGPU is still real silicon doing real parallel work
        assert dev(kind="integrated").usable

    def test_a_software_rasteriser_is_NOT(self):
        # THE case. llvmpipe IS the processor; offloading to it adds a layer
        # to reach the hardware already doing the job, and reports success.
        assert not LLVMPIPE.usable

    def test_a_virtual_device_is_NOT(self):
        # a paravirtualised device passes through to a host GPU we cannot
        # reason about; being wrong there hangs rather than slows
        assert not dev(kind="virtual").usable

    def test_an_unknown_type_is_NOT(self):
        # a Vulkan version reporting something we do not recognise is not an
        # invitation to guess
        assert not dev(kind="other").usable


class TestRanking:
    def test_discrete_beats_integrated(self, devices):
        devices([INTEL_IGPU, NVK_3050])
        assert vulkan.best_device().kind == "discrete"

    def test_order_reported_by_the_driver_does_not_decide(self, devices):
        # the loader listed the iGPU first on the development machine
        devices([INTEL_IGPU, NVK_3050])
        first = vulkan.best_device()
        devices([NVK_3050, INTEL_IGPU])
        assert vulkan.best_device() == first

    def test_software_is_never_chosen_even_when_alone(self, devices):
        devices([LLVMPIPE])
        assert vulkan.best_device() is None

    def test_software_is_never_chosen_even_with_the_largest_heap(self, devices):
        # llvmpipe reports MORE memory than either real device
        devices([INTEL_IGPU, NVK_3050, LLVMPIPE])
        assert vulkan.best_device().kind == "discrete"

    def test_an_integrated_gpu_is_used_when_it_is_all_there_is(self, devices):
        devices([INTEL_IGPU, LLVMPIPE])
        assert vulkan.best_device() == INTEL_IGPU

    def test_nothing_usable_yields_nothing(self, devices):
        devices([LLVMPIPE, dev(kind="virtual")])
        assert vulkan.best_device() is None
        assert vulkan.usable_devices() == []


class TestTheReportBenchRenders:
    def test_lists_every_device_including_unusable_ones(self, devices):
        # a user seeing only "1 device" on a machine with three would think
        # detection was broken; show all, mark which counts
        devices([INTEL_IGPU, NVK_3050, LLVMPIPE])
        r = vulkan.report()
        assert len(r["devices"]) == 3
        assert [d["usable"] for d in r["devices"]] == [True, True, False]

    def test_names_the_device_that_would_be_used(self, devices):
        devices([INTEL_IGPU, NVK_3050, LLVMPIPE])
        assert "3050" in vulkan.report()["would_use"]

    def test_says_nothing_would_be_used_when_nothing_qualifies(self, devices):
        devices([LLVMPIPE])
        assert vulkan.report()["would_use"] is None

    def test_a_machine_with_no_vulkan_reports_cleanly(self, devices):
        devices([])
        r = vulkan.report()
        assert r["devices"] == []
        assert r["would_use"] is None
        assert r["loader_present"] is False

    def test_the_report_is_json_safe(self, devices):
        import json
        devices([INTEL_IGPU, NVK_3050, LLVMPIPE])
        json.dumps(vulkan.report())


class TestItNeverTakesTheAppDown:
    """A missing loader, a broken driver, or a Vulkan version we do not expect
    must all mean 'run on the processor' -- which is what was happening anyway.
    """

    def test_no_loader_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(vulkan, "load_loader", lambda: None)
        assert vulkan.enumerate_devices() == []
        assert vulkan.best_device() is None
        assert vulkan.available() is False

    def test_a_loader_that_cannot_create_an_instance(self, monkeypatch):
        class Broken:
            def vkCreateInstance(self, *a):
                return -3  # VK_ERROR_INITIALIZATION_FAILED
            def vkDestroyInstance(self, *a):
                return None
        monkeypatch.setattr(vulkan, "load_loader", lambda: Broken())
        assert vulkan.enumerate_devices() == []

    def test_a_loader_that_raises(self, monkeypatch):
        class Explodes:
            def vkCreateInstance(self, *a):
                raise OSError("driver fell over")
            def vkDestroyInstance(self, *a):
                return None
        monkeypatch.setattr(vulkan, "load_loader", lambda: Explodes())
        assert vulkan.enumerate_devices() == []

    def test_a_loader_reporting_zero_devices(self, monkeypatch):
        import ctypes
        class Empty:
            def vkCreateInstance(self, *a):
                return 0
            def vkEnumeratePhysicalDevices(self, _inst, count, _out=None):
                ctypes.cast(count, ctypes.POINTER(ctypes.c_uint32)).contents.value = 0
                return 0
            def vkDestroyInstance(self, *a):
                return None
        monkeypatch.setattr(vulkan, "load_loader", lambda: Empty())
        assert vulkan.enumerate_devices() == []


class TestLabels:
    def test_the_device_name_is_used_when_present(self):
        assert NVK_3050.label == NVK_3050.name

    def test_a_nameless_device_still_reads_as_something(self):
        # an empty string in the UI reads as a rendering fault
        assert dev(name="", vendor="AMD").label == "AMD graphics"

    def test_the_vendor_is_resolved_to_a_name_people_know(self, devices):
        devices([NVK_3050, INTEL_IGPU])
        assert {d["vendor"] for d in vulkan.report()["devices"]} == {"NVIDIA", "Intel"}
