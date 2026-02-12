# JSBSim DCS Fork — Overview of Changes

**Branch:** `DCS-WIP-hacky` (Zaretto/jsbsim)
**Base:** JSBSim-Team/jsbsim, synchronised through September 2025
**Author:** Richard Harrison
**Period:** April 2018 — February 2026

---

## Purpose

This fork adapts JSBSim for use as a flight dynamics engine inside DCS World, linked as a
static library into the acEFM External Flight Model DLL. DCS provides the simulation
environment (atmosphere, propagation, inertial reference) while JSBSim computes aerodynamic
forces, propulsion, systems, and ground reactions.

---

## What Changed in JSBSim

### 1. Selective Model Execution

The core modification. JSBSim's main simulation loop (`FGFDMExec::Run()`) normally
iterates through all subsystem models sequentially. In DCS mode, a `switch` statement
selectively runs only the models that DCS needs:

**Models run by JSBSim:**
Systems, Input, Mass Balance, Propulsion, Aerodynamics, Ground Reactions,
External Reactions, Aircraft, Accelerations, Output

**Models skipped (DCS provides externally):**
Propagate, Inertial, Atmosphere, Winds, Auxiliary, Buoyant Forces

A global flag `DCS__active` toggles between DCS mode and standalone mode, allowing the
same library to serve both the EFM and the TestPlane harness.

### 2. External Data Setters

Since several subsystems are bypassed, the DCS interface must inject their data directly.
New public setter methods were added to three key classes:

**FGAtmosphere** — `SetSoundSpeed()`, `SetPressure()`, `SetDensity()`, `SetDensitySL()`

**FGAuxiliary** — `SetMach()`, `SetAlpha()`, `SetBeta()`, `SetVcas()`, `SetVtrueFPS()`,
`SetQBar()`, `SetNx()`, `SetNy()`, `SetNz()`, `Setadot()`, `Setbdot()`.
`UpdateWindMatrices()` was also made public so airspeed and wind calculations can be
triggered explicitly.

**FGAerodynamics** — `SetBI2Vel()`, `SetCI2Vel()` for rotary damping coefficients.

**FGPropagate** — `VState` (vehicle state struct) made publicly accessible so the DCS
interface can directly set position, velocity, and attitude.

### 3. Relocated Airspeed Calculations

Airspeed-derived quantities (Mach, VCAS, VEAS, pitot pressure, TAT, Reynolds number)
were moved from `FGAuxiliary::Run()` into `FGAuxiliary::UpdateWindMatrices()`. Since the
Auxiliary model is skipped in DCS mode, this relocation ensures these calculations still
execute when called explicitly from the DCS interface layer.

### 4. Disabled Internal State Updates

`FGPropagate::SetAltitudeASL()` no longer calls `UpdateVehicleState()`. When DCS sets
altitude, JSBSim must not recompute the full vehicle state — DCS owns propagation.

### 5. Build System

JSBSim is built as a **static library** (`JSBSim.lib`) rather than a standalone
executable. The Visual Studio project includes a `JSBSimRelease|x64` configuration
matching the parent acEFM solution. Key build settings:

- Visual Studio 2022 toolset (v143), C++17
- `JSBSIM_STATIC_LINK`, `XML_STATIC`, `HAVE_EXPAT_CONFIG_H` preprocessor definitions
- Floating-point model set to `Precise` (not `Fast`)
- Optimisation disabled for debugging during development
- `ws2_32.lib` linked for the telnet socket interface

### 6. Telnet Interface Improvements

The property browser (`get` command) no longer requires the simulation to be in HOLD
mode. The handler temporarily pauses the sim, performs the catalog query, then resumes —
enabling live property inspection via Symon without interrupting DCS.

### 7. Autotest Support

Flexible path management for the TestPlane autotest system:

- New CLI options: `--aircraft-path`, `--engine-path`, `--systems-path`, `--init-path`
- `AddModelToPath` flag to control whether the model name is appended as a subdirectory
- Separate `InitPath` for initialisation files independent of the aircraft directory
- Output file paths that are already absolute are not prepended with the output folder

### 8. Standalone Instrumentation (WIP)

The standalone `main()` in `JSBSim.cpp` has been replaced with Windows high-precision
timer instrumentation (`QueryPerformanceCounter`) for benchmarking. Frame rate
calculation is available in `FGScript` via `REPORT_FRAME_RATE`. This is acknowledged
as temporary/WIP code.

---

## How acEFM Uses These Changes

The acEFM project (`flyt-EFM-dcsJSBSim/`) is the calling side of all the JSBSim
modifications. It implements the DCS EFM API entry points and translates between DCS
conventions (SI units, Y-up) and JSBSim conventions (Imperial units, Z-down).

### Per-Frame Calling Sequence

DCS calls the EFM entry points in this order each simulation frame:

```
1. ed_fm_set_atmosphere()              → Inject atmosphere
2. ed_fm_set_current_state()           → Inject world-frame accelerations
3. ed_fm_set_current_state_body_axis() → Inject body-frame state (primary)
4. ed_fm_set_command()                 → Inject control inputs
5. ed_fm_simulate(dt)                  → Run JSBSim (selective models)
6. ed_fm_add_local_force()             → Read computed forces
7. ed_fm_add_local_moment()            → Read computed moments
8. ed_fm_set_draw_args()               → Update animations
```

### Atmosphere Injection (`ed_fm_set_atmosphere`)

DCS provides atmospheric conditions in SI units. `DCS_interface.cpp` converts and passes
them through the `FGJSBsim` wrapper to the JSBSim setter methods:

| DCS Parameter | Conversion | JSBSim Setter |
|---------------|------------|---------------|
| Density (kg/m^3) | x 0.00194032 | `Atmosphere->SetDensity()` (slugs/ft^3) |
| Pressure (Pa) | x 0.02088527 | `Atmosphere->SetPressure()` (lbf/ft^2) |
| Speed of sound (m/s) | x 3.28084 | `Atmosphere->SetSoundSpeed()` (ft/s) |
| Altitude (m) | x 3.28084 | `Propagate->SetAltitudeASL()` (ft) |

A vertical speed (VSI) is also computed from the altitude delta between frames and
written to the property tree as `/fdm/jsbsim/velocities/vsi-instant-ftmin`.

### Body-Axis State Injection (`ed_fm_set_current_state_body_axis`)

This is the primary state injection entry point — it feeds the complete aircraft state
into JSBSim each frame. The flow within `DCS_interface.cpp`:

**1. True airspeed** — Computed as the magnitude of the wind-relative body velocity
vector, converted to ft/s, and set via `Auxiliary->SetVtrueFPS()`.

**2. Angle of attack and sideslip** — DCS provides alpha and beta in radians. Converted
to degrees and set via `Auxiliary->SetAlpha()` and `Auxiliary->SetBeta()`.

**3. Alpha/beta rates** — Computed by finite-differencing alpha and beta between frames
(dividing by dt), then set via `Auxiliary->Setadot()` and `Auxiliary->Setbdot()`.

**4. Body angular rates (P, Q, R)** — Set on both `Auxiliary` (via input struct
`in.vPQR`) and `Propagate` (via `SetPQR()`). The DCS Y-axis (yaw) is negated to match
JSBSim's Z-down convention.

**5. Body velocities (U, V, W)** — Wind-relative body velocities (DCS airframe velocity
minus wind velocity), converted to ft/s, set on `Auxiliary->in.vUVW`. Again DCS Y-axis
is negated for the Z-down convention.

**6. Wind matrices** — `Auxiliary->UpdateWindMatrices()` is called explicitly to compute
derived quantities (Mach, VCAS, VEAS, pitot pressure, TAT, Reynolds number) that would
normally be computed inside the skipped `Auxiliary::Run()`.

**7. Attitude** — Roll, pitch, yaw (radians) are composed into an `FGQuaternion`. The
attitude is written into `Propagate->VState` via `GetVState()` / `SetVState()` (using
the public VState access).

**8. Dynamic pressure and aero reference ratios** — Computed from density and true
airspeed:
- `qbar = 0.5 * rho * Vt^2` → `Auxiliary->SetQBar()`
- `bi2vel = wingspan / (2 * Vt)` → `Aerodynamics->SetBI2Vel()`
- `ci2vel = chord / (2 * Vt)` → `Aerodynamics->SetCI2Vel()`

**9. Auxiliary run** — `Auxiliary->Run(false)` is called to compute any remaining
derived quantities before the main simulation step.

### World-Frame Accelerations (`ed_fm_set_current_state`)

Load factors (Nx, Ny, Nz) are extracted from DCS world-frame accelerations, converted
from m/s^2 to ft/s^2, and set via `Auxiliary->SetNx()`, `SetNy()`, `SetNz()`.

### Force and Moment Retrieval

After `ed_fm_simulate(dt)` runs the JSBSim selective model loop, DCS reads back the
computed forces and moments via the property tree:

**Forces** (lbs to Newtons, x 4.448):
| JSBSim Property | DCS Axis | Note |
|----------------|----------|------|
| `forces/fbx-total-lbs` | X (forward) | Direct mapping |
| `forces/fbz-total-lbs` | Y (up) | Negated (Z-down to Y-up) |
| `forces/fby-total-lbs` | Z (right) | Direct mapping |

**Moments** (lbf-ft to N-m, x 1.356):
| JSBSim Property | DCS Axis | Note |
|----------------|----------|------|
| `moments/l-total-lbsft` | X (roll) | Direct mapping |
| `moments/n-total-lbsft` | Y (yaw) | Negated |
| `moments/m-total-lbsft` | Z (pitch) | Direct mapping |

### Cockpit and Animations

Cockpit parameters and draw arguments are driven by configurable bindings defined in
`aceFMconfig.xml`. Each frame, the `Cockpit` and `DrawArguments` classes iterate their
bound items, read the corresponding JSBSim property values via `fgGetDouble()`, apply
scale factors and delta-change thresholds, and push updates to the DCS cockpit parameter
API or draw argument array.

### TestPlane and `DCS__active`

`TestPlane.exe` uses the same EFM entry points but can toggle `DCS__active`:

- **DCS mode** (`DCS__active = 1`, default) — The EFM calling sequence above applies.
  TestPlane injects synthetic atmosphere and state data, runs `ed_fm_simulate()`, and
  reads back results. Used for integration testing with real aircraft models.

- **Standalone mode** (`DCS__active = 0`) — All JSBSim models run (including
  propagation, atmosphere, etc.). JSBSim acts as a self-contained simulator driven by
  script files. Used for pure JSBSim model validation without the DCS interface layer.

---

## Coordinate System Mapping

The axis convention translation between DCS and JSBSim is a recurring theme:

| Axis | DCS | JSBSim |
|------|-----|--------|
| Forward | +X | +X |
| Up | +Y | -Z |
| Right | +Z | +Y |

Angular rates and moments follow the same remapping with appropriate sign changes.
All unit conversions (SI to Imperial) are performed in `DCS_interface.cpp`.

---

## JSBSim Files Modified (DCS-Specific)

| Area | Files |
|------|-------|
| Core engine | `FGFDMExec.cpp`, `FGFDMExec.h` |
| Atmosphere | `FGAtmosphere.h` |
| Auxiliary | `FGAuxiliary.h`, `FGAuxiliary.cpp` |
| Aerodynamics | `FGAerodynamics.h` |
| Propagation | `FGPropagate.h` |
| Telnet/IO | `FGInputSocket.cpp`, `FGScript.cpp`, `FGOutputFile.h` |
| Init | `FGInitialCondition.cpp` |
| Standalone | `JSBSim.cpp` |
| SimGear | `compiler.h`, `props/props.cxx` |
| Build | `JSBSim.vcxproj`, `.vcxproj.filters`, `JSBSim.sln`, `.gitignore` |

## acEFM Files (Integration Layer)

| File | Role |
|------|------|
| `DCS_interface.cpp` | DCS EFM API entry points; unit conversion; state injection |
| `DCS_interface.h` | Cockpit, DrawArguments, AnimateItem classes |
| `JSBSim_interface.cpp` | FGJSBsim wrapper: init, model loading, subsystem access |
| `JSBSim_interface.h` | FGJSBsim class with setter wrappers for each JSBSim method |
| `TestPlane.cpp` | Standalone harness; DCS__active toggle; synthetic state injection |

---

## Future plans

### Upstream Synchronisation

The fork was last brought current with upstream JSBSim-Team in April 2024 (`a58ca666`); this
needs to be done again soon.

Once I've got a good feel for what we're doing I intend to write a proposal detailing a plan to 
integrate these changes back into master. This is probably still a good way off as it's taking a
while to understand how DCS works and how best to proceed to a correct implementation.


