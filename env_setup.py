# env_setup.py
# =============================================================================
# GPIO + ENVIRONMENT INITIALIZATION
# =============================================================================
import os
import sys
import subprocess
import types

def initialize_gpio():
    """Initialize GPIO pin factory before any GPIO operations"""
    print("Initializing GPIO...")

    gpio_libs = []
    try:
        import lgpio
        gpio_libs.append(('lgpio', lgpio))
        print("✓ lgpio available")
    except ImportError:
        print("✗ lgpio not available")

    try:
        import pigpio
        gpio_libs.append(('pigpio', pigpio))
        print("✓ pigpio available")
    except ImportError:
        print("✗ pigpio not available")

    try:
        import RPi.GPIO
        gpio_libs.append(('RPi.GPIO', RPi.GPIO))
        print("✓ RPi.GPIO available")
    except ImportError:
        print("✗ RPi.GPIO not available")

    if not gpio_libs:
        print("❌ ERROR: No GPIO libraries available!")
        return False

    try:
        import gpiozero
        print("✓ gpiozero imported")

        if any(name == 'lgpio' for name, _ in gpio_libs):
            try:
                os.environ['GPIOZERO_PIN_FACTORY'] = 'lgpio'
                from gpiozero.pins.lgpio import LGPIOFactory
                gpiozero.Device.pin_factory = LGPIOFactory()
                print("✓ GPIO initialized with lgpio")
                return True
            except Exception as e:
                print(f"✗ lgpio factory failed: {e}")

        if any(name == 'pigpio' for name, _ in gpio_libs):
            try:
                os.environ['GPIOZERO_PIN_FACTORY'] = 'pigpio'
                from gpiozero.pins.pigpio import PiGPIOFactory
                gpiozero.Device.pin_factory = PiGPIOFactory()
                print("✓ GPIO initialized with pigpio")
                return True
            except Exception as e:
                print(f"✗ pigpio factory failed: {e}")

        if any(name == 'RPi.GPIO' for name, _ in gpio_libs):
            try:
                os.environ['GPIOZERO_PIN_FACTORY'] = 'rpigpio'
                from gpiozero.pins.rpigpio import RPiGPIOFactory
                gpiozero.Device.pin_factory = RPiGPIOFactory()
                print("✓ GPIO initialized with RPi.GPIO")
                return True
            except Exception as e:
                print(f"✗ RPi.GPIO factory failed: {e}")

        os.environ['GPIOZERO_PIN_FACTORY'] = 'mock'
        from gpiozero.pins.mock import MockFactory
        gpiozero.Device.pin_factory = MockFactory()
        print("⚠ WARNING: Using mock GPIO - hardware will not work!")
        return True

    except ImportError as e:
        print(f"❌ Failed to import gpiozero: {e}")
        return False


def setup_environment():
    """Setup environment variables and block pip/git"""
    # Ultralytics & pip settings
    os.environ['ULTRALYTICS_OFFLINE'] = 'True'
    os.environ['YOLO_VERBOSE'] = 'False'
    os.environ['PIP_NO_DEPS'] = 'True'
    os.environ['PYTHONNOUSERSITE'] = 'True'
    os.environ['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
    os.environ['PIP_NO_INDEX'] = '1'
    os.environ['PIP_NO_CACHE_DIR'] = '1'
    os.environ.setdefault("OPENBLAS_CORETYPE", "ARMV8")

    # Block dangerous subprocess calls
    BLOCK_TOKENS = (
        " pip ", " pip3 ", "python -m pip", " -m pip ",
        "git ", "/git ", " git+https://github.com/Tencent/ncnn",
        "git submodule", " git clone "
    )

    def _should_block(cmd, shell=False):
        if isinstance(cmd, (list, tuple)):
            s = " ".join(str(x) for x in cmd)
        else:
            s = str(cmd or "")
        s = f" {s.strip()} "
        if shell:
            return any(tok in s for tok in BLOCK_TOKENS)
        return any(tok in s for tok in BLOCK_TOKENS)

    def _blocked(name, cmd):
        raise RuntimeError(f"Blocked external install/clone at runtime via {name}: {cmd}")

    # Patch subprocess APIs
    _orig_run = subprocess.run
    _orig_popen = subprocess.Popen
    _orig_check_call = subprocess.check_call
    _orig_check_output = subprocess.check_output

    def _guard_run(*args, **kwargs):
        cmd = kwargs.get("args", args[0] if args else None)
        if _should_block(cmd, kwargs.get("shell", False)):
            _blocked("subprocess.run", cmd)
        return _orig_run(*args, **kwargs)

    def _guard_popen(*args, **kwargs):
        cmd = kwargs.get("args", args[0] if args else None)
        if _should_block(cmd, kwargs.get("shell", False)):
            _blocked("subprocess.Popen", cmd)
        return _orig_popen(*args, **kwargs)

    def _guard_check_call(*args, **kwargs):
        cmd = kwargs.get("args", args[0] if args else None)
        if _should_block(cmd, kwargs.get("shell", False)):
            _blocked("subprocess.check_call", cmd)
        return _orig_check_call(*args, **kwargs)

    def _guard_check_output(*args, **kwargs):
        cmd = kwargs.get("args", args[0] if args else None)
        if _should_block(cmd, kwargs.get("shell", False)):
            _blocked("subprocess.check_output", cmd)
        return _orig_check_output(*args, **kwargs)

    subprocess.run = _guard_run
    subprocess.Popen = _guard_popen
    subprocess.check_call = _guard_check_call
    subprocess.check_output = _guard_check_output

    # Block os.system
    _orig_system = os.system
    def _guard_system(cmd):
        if _should_block(cmd, shell=True):
            _blocked("os.system", cmd)
        return _orig_system(cmd)
    os.system = _guard_system

    # Torchvision ONNX safeguard
    os.environ.setdefault("TORCHVISION_DISABLE_NMS_EXPORT", "1")
    if "torchvision.ops._register_onnx_ops" not in sys.modules:
        _tv_dummy = types.ModuleType("torchvision.ops._register_onnx_ops")
        _tv_dummy._register_custom_op = lambda *a, **k: None
        sys.modules["torchvision.ops._register_onnx_ops"] = _tv_dummy

    print("✓ Environment setup complete (pip/git blocked, GPIO set)")
