"""What graphics hardware this machine can actually compute on.

Asked through Vulkan, because the Vulkan loader ships with the graphics driver
rather than with a toolkit. On the machine this was written for -- a laptop with
no NVIDIA packages installed at all -- it already reports:

    Intel(R) UHD Graphics (TGL GT1)                 integrated GPU
    NVIDIA GeForce RTX 3050 Ti Laptop (NVK GA107)   discrete GPU
    llvmpipe (LLVM 22.1.8)                          CPU, software

That second line is the point. `NVK` is Mesa's open-source Vulkan driver for
NVIDIA cards, so the discrete GPU is reachable without a single proprietary
package. CUDA would have reached neither device on that machine; Vulkan reaches
both, plus AMD, plus Intel, through drivers the user already has.

── Two things learned by running this rather than reasoning about it ──

**llvmpipe must be excluded.** It is a software rasteriser: the CPU pretending
to be a GPU. Offloading to it would be slower than the CPU path already in use
while reporting success -- a thing that passes every check and does the wrong
thing.

**Reported memory is not VRAM.** Both real devices above claim 12.4 GB, which is
system memory; the 3050 Ti has 4 GB. Heap size cannot decide whether a device is
worth using, so `kind` does.

Nothing here may raise. A machine with no loader, a broken driver, or a Vulkan
version we do not expect must produce an empty list and leave the app on the CPU.
"""

from __future__ import annotations

import ctypes as C
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# VkPhysicalDeviceType
_TYPE_OTHER, _TYPE_INTEGRATED, _TYPE_DISCRETE, _TYPE_VIRTUAL, _TYPE_CPU = range(5)

_KIND = {
    _TYPE_OTHER: "other",
    _TYPE_INTEGRATED: "integrated",
    _TYPE_DISCRETE: "discrete",
    _TYPE_VIRTUAL: "virtual",
    _TYPE_CPU: "software",
}

# PCI vendor ids, for a label a person recognises
_VENDORS = {
    0x8086: "Intel", 0x1002: "AMD", 0x10DE: "NVIDIA",
    0x13B5: "ARM", 0x5143: "Qualcomm", 0x1010: "Imagination",
}

_LOADERS = ("libvulkan.so.1", "vulkan-1.dll", "libvulkan.1.dylib", "libvulkan.so")


@dataclass(frozen=True)
class VulkanDevice:
    """one device the Vulkan loader can see."""
    name: str
    vendor: str
    kind: str              # discrete | integrated | software | virtual | other
    heap_bytes: int
    api_version: str

    @property
    def usable(self) -> bool:
        """whether offloading to this would be an improvement.

        Software rasterisers are excluded: llvmpipe IS the processor, so moving
        work onto it adds a translation layer to reach the hardware already
        doing the job. `virtual` is excluded for the same reason -- a
        paravirtualised device in a VM passes through to a host GPU we cannot
        reason about, and being wrong there is a hang rather than a slowdown.
        """
        return self.kind in ("discrete", "integrated")

    @property
    def label(self) -> str:
        """what to show a person: the name already contains the vendor."""
        return self.name or f"{self.vendor} graphics"


# ── the ctypes surface ────────────────────────────────────────────────────
# Written out rather than pulled from a binding because this must run inside a
# frozen bundle with no build step, and it is the only Vulkan call we make.

class _AppInfo(C.Structure):
    _fields_ = [
        ("sType", C.c_int), ("pNext", C.c_void_p),
        ("pApplicationName", C.c_char_p), ("applicationVersion", C.c_uint32),
        ("pEngineName", C.c_char_p), ("engineVersion", C.c_uint32),
        ("apiVersion", C.c_uint32),
    ]


class _InstanceInfo(C.Structure):
    _fields_ = [
        ("sType", C.c_int), ("pNext", C.c_void_p), ("flags", C.c_uint32),
        ("pApplicationInfo", C.POINTER(_AppInfo)),
        ("enabledLayerCount", C.c_uint32), ("ppEnabledLayerNames", C.c_void_p),
        ("enabledExtensionCount", C.c_uint32), ("ppEnabledExtensionNames", C.c_void_p),
    ]


class _Props(C.Structure):
    """VkPhysicalDeviceProperties.

    The field order matters and is easy to get wrong: the first draft read
    deviceType from offset 12 instead of 16 and reported every device as type
    39520 with an empty name. Declaring the struct rather than indexing a byte
    buffer is what stops that being possible.
    """
    _fields_ = [
        ("apiVersion", C.c_uint32), ("driverVersion", C.c_uint32),
        ("vendorID", C.c_uint32), ("deviceID", C.c_uint32),
        ("deviceType", C.c_uint32), ("deviceName", C.c_char * 256),
        ("pipelineCacheUUID", C.c_uint8 * 16),
        ("_limits", C.c_uint8 * 504), ("_sparse", C.c_uint8 * 20),
    ]


class _MemoryHeap(C.Structure):
    _fields_ = [("size", C.c_uint64), ("flags", C.c_uint32), ("_pad", C.c_uint32)]


class _MemoryProps(C.Structure):
    _fields_ = [
        ("memoryTypeCount", C.c_uint32),
        ("memoryTypes", C.c_uint8 * (32 * 8)),
        ("memoryHeapCount", C.c_uint32),
        ("memoryHeaps", _MemoryHeap * 16),
    ]


_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1


def load_loader():
    """the Vulkan loader, or None. Never raises.

    Its presence is the whole reason this backend was chosen: it arrives with
    the graphics driver, so a user who can run any 3D application already has
    it, and there is nothing for them to install.
    """
    for name in _LOADERS:
        try:
            return C.CDLL(name)
        except OSError:
            continue
    return None


def available() -> bool:
    """is Vulkan present at all?"""
    return load_loader() is not None


def enumerate_devices() -> list[VulkanDevice]:
    """every device the loader can see, in the order it reports them.

    Returns an empty list for every failure -- no loader, no instance, a driver
    that misbehaves. A machine that cannot answer this question is a machine
    that runs on the processor, which is what it was already doing.
    """
    vk = load_loader()
    if vk is None:
        return []

    instance = C.c_void_p()
    try:
        app = _AppInfo(0, None, b"ThinkStack", 1, b"ThinkStack", 1, 1 << 22)
        info = _InstanceInfo(_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, None, 0,
                             C.pointer(app), 0, None, 0, None)
        if vk.vkCreateInstance(C.byref(info), None, C.byref(instance)) != 0:
            logger.debug("vulkan: could not create an instance")
            return []
    except Exception as e:  # noqa: BLE001 - a driver may do anything
        logger.debug("vulkan: instance creation failed: %s", e)
        return []

    try:
        count = C.c_uint32()
        if vk.vkEnumeratePhysicalDevices(instance, C.byref(count), None) != 0:
            return []
        if not count.value:
            return []

        handles = (C.c_void_p * count.value)()
        if vk.vkEnumeratePhysicalDevices(instance, C.byref(count), handles) != 0:
            return []

        found: list[VulkanDevice] = []
        for handle in handles:
            try:
                found.append(_describe(vk, handle))
            except Exception as e:  # noqa: BLE001 - one bad device is not fatal
                logger.debug("vulkan: skipped a device: %s", e)
        return found
    finally:
        try:
            vk.vkDestroyInstance(instance, None)
        except Exception:  # noqa: BLE001 - nothing useful to do while cleaning up
            pass


def _describe(vk, handle) -> VulkanDevice:
    props = _Props()
    vk.vkGetPhysicalDeviceProperties(C.c_void_p(handle), C.byref(props))

    mem = _MemoryProps()
    vk.vkGetPhysicalDeviceMemoryProperties(C.c_void_p(handle), C.byref(mem))
    heaps = [mem.memoryHeaps[i].size for i in range(min(mem.memoryHeapCount, 16))]

    v = props.apiVersion
    return VulkanDevice(
        name=props.deviceName.decode("utf-8", "replace").strip(),
        vendor=_VENDORS.get(props.vendorID, f"0x{props.vendorID:04x}"),
        kind=_KIND.get(props.deviceType, "other"),
        heap_bytes=max(heaps, default=0),
        api_version=f"{v >> 22}.{(v >> 12) & 0x3FF}",
    )


def usable_devices() -> list[VulkanDevice]:
    """devices worth offloading to, best first.

    Discrete before integrated, because a discrete part has its own memory and
    far more of it. Everything else is dropped -- see `VulkanDevice.usable`.
    """
    order = {"discrete": 0, "integrated": 1}
    return sorted(
        (d for d in enumerate_devices() if d.usable),
        key=lambda d: (order.get(d.kind, 9), -d.heap_bytes),
    )


def best_device() -> VulkanDevice | None:
    """the device acceleration would use, or None if there is nothing worth it."""
    devices = usable_devices()
    return devices[0] if devices else None


def report() -> dict:
    """what Bench shows: every device seen, and which one would be used."""
    devices = enumerate_devices()
    best = None
    order = {"discrete": 0, "integrated": 1}
    usable = sorted((d for d in devices if d.usable),
                    key=lambda d: (order.get(d.kind, 9), -d.heap_bytes))
    if usable:
        best = usable[0]

    return {
        "loader_present": bool(devices) or available(),
        "devices": [
            {
                "name": d.label, "vendor": d.vendor, "kind": d.kind,
                "usable": d.usable, "api": d.api_version,
            }
            for d in devices
        ],
        "would_use": best.label if best else None,
    }
