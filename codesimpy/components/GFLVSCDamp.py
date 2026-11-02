
"""Grid-following converter with LVRT and active damping, without outer loop."""

import sympy as sp
from ..core import Device


class GFLVSCDamp(Device):
    def __init__(self, Vb, Sb, index):
        super().__init__(Vb, Sb, "Current", index, {
            "L": 3.25e-4, "Kicc": 5.0, "Kpcc": 0.1,
            "KpPll": 0.01, "KiPll": 0.5,
            "wPllMin": 0.8, "wPllMax": 1.2,
            "KawPll": 5.0, "w0": 1.0,
            "K1": 1.5, "Imax": 1.5,
            "Id2": 1.2, "Vth": 0.9,
            "Kad": 0.05, "wAD": 10.0,
            # Retained for system-level reference and signal reporting.  This
            # converter has no outer voltage loop, so Vctrl defaults to off.
            "Vctrl": 0.0, "Vref": 1.0, "Kq": 1.0,
        }, (
            "id", "iq", "xPIccd", "xPIccq",
            "theta", "xPLL", "vFD", "vFQ",
        ), ("Idref", "Iqref"))

    def getStateAndOutputEquationsSym(self):
        i = sp.Matrix(self.x[0:2])
        xcc = sp.Matrix(self.x[2:4])
        theta, xPLL = self.x[4:6]
        vf = sp.Matrix(self.x[6:8])

        iref0 = sp.Matrix(self.uref)
        vabc = sp.Matrix(self.u)

        p = lambda name: self.p[name]["sym"]
        pos = lambda x: (x + sp.Abs(x)) / 2

        def clip(x, lower, upper):
            return lower + pos(x - lower) - pos(x - upper)

        J = sp.Matrix([[0, -1], [1, 0]])
        R = sp.Matrix([
            [sp.cos(theta), -sp.sin(theta)],
            [sp.sin(theta),  sp.cos(theta)],
        ])

        # PCC voltage in PLL dq coordinates
        v = R.T * vabc
        vd, vq = v
        vmag = sp.sqrt(v.dot(v))

        # PLL
        wRaw = p("w0") + p("KpPll") * vq + p("KiPll") * xPLL
        w = clip(wRaw, p("wPllMin"), p("wPllMax"))
        dxPLL = vq + p("KawPll") * (w - wRaw)

        # Normal current priority
        Imax = p("Imax")
        idNormal = clip(iref0[0], 0, Imax)
        iqLimit = sp.sqrt(pos(Imax**2 - idNormal**2))
        iqNormal = clip(iref0[1], -iqLimit, iqLimit)
        iNormal = sp.Matrix([idNormal, iqNormal])

        # LVRT reactive-current priority
        iqLvrt = clip(
            -p("K1") * (p("Vth") - vmag), -Imax, Imax
        )
        idLimit = sp.sqrt(pos(Imax**2 - iqLvrt**2))
        idLvrt = clip(p("Id2"), 0, idLimit)
        iLvrt = sp.Matrix([idLvrt, iqLvrt])

        # Smooth LVRT transition
        lvrtMode = (
            1 + sp.tanh(50 * (p("Vth") - vmag))
        ) / 2

        iref = (1 - lvrtMode) * iNormal + lvrtMode * iLvrt

        # Inner current PI controller
        ei = iref - i
        L = p("L")

        # High-pass PCC-voltage active damping
        dvf = p("wAD") * (v - vf)
        vAD = p("Kad") * (v - vf)

        # Converter voltage command
        vconv = (
            v + w * L * J * i
            + p("Kpcc") * ei
            + p("Kicc") * xcc
            + vAD
        )

        # Filter-inductor dynamics
        di = (vconv - v) / L - w * J * i

        # Current PI integrator
        dxcc = ei

        # Stationary-frame output current
        iout = R * i

        return (
            list(di) + list(dxcc)
            + [w, dxPLL] + list(dvf),
            list(iout)
        )

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [
            P - V * self.uref[0],
            Q + V * self.uref[1],
        ]

    def getFInit(self):
        return sp.Matrix.vstack(
            self.f[:4, :],
            self.f[5:, :],
        )

    def initFromPowerFlow(self, V, theta, P, Q):
        i = sp.Matrix([P / V, -Q / V])
        return (
            list(i) + [0.0, 0.0]
            + [theta, 0.0, V, 0.0]
        )
