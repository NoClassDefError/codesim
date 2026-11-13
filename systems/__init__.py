"""Ready-to-run CodeSim systems, named ``Network__Unit__Unit``.

``Network``: ``SMIB`` one unit + infinite bus; ``CIGRE4`` four-node reduction of the CIGRE MV feeder
(infinite bus, 7, 8, 9; loads omitted); ``CIGRE14`` full CIGRE MV feeder. ``Unit`` is a converter with its
filter, named ``Role_Control_Limiter_Filter`` as in :mod:`codesimpy.components`, or ``SG``. Each class is one fixed configuration; its docstring gives the full
description.
"""

from .cigre14 import CIGRE14__GFM_A_C_LC__GFL_C_F_L
from .cigre4_gfm_a_c_lc import CIGRE4__GFM_A_C_LC__GFL_C_F_L
from .smib_gfl_c_f_l import SMIB__GFL_C_F_L
from .smib_gfm_a_c_l import SMIB__GFM_A_C_L
from .smib_sg import SMIB__SG

__all__ = [
    "SMIB__GFM_A_C_L", "SMIB__GFL_C_F_L", "SMIB__SG",
    "CIGRE4__GFM_A_C_LC__GFL_C_F_L",
    "CIGRE14__GFM_A_C_LC__GFL_C_F_L",
]
