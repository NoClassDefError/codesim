"""CodeSim device models.

Converters use serial names ``Role_Control_Limiter_Filter``:

* Role: ``GFM`` grid-forming, ``GFL`` grid-following.
* Control: ``A`` virtual admittance + current PI; ``C`` GFL current references + current PI.
* Limiter: ``C`` circular limit on the current reference; ``F`` GFL FRT/LVRT current priority.
* Filter: ``LC`` the device holds its terminal capacitor; ``L`` it does not.

The full description is in each class docstring.
"""

from .capacitor import Capacitor
from .gfl_c_f_l import GFL_C_F_L
from .gfm_a_c_l import GFM_A_C_L
from .gfm_a_c_lc import GFM_A_C_LC
from .infbus import Infbus
from .sg import SG
from .zero_current import ZeroCurrent

__all__ = [
    "Capacitor", "Infbus", "SG", "ZeroCurrent",
    "GFM_A_C_LC", "GFM_A_C_L", "GFL_C_F_L",
]
