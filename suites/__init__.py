from .dacapo import DaCapoSuite
from .dacapo_mdo import DaCapoMDOSuite
from .renaissance import RenaissanceSuite

SUITES = {
    "dacapo": DaCapoSuite,
    "dacapo-mdo": DaCapoMDOSuite,
    "renaissance": RenaissanceSuite,
}
