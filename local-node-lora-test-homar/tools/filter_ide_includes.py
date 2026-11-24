"""Omit known missing Arduino-ESP32 include directories from IDE metadata."""

import os

Import("env")

# PlatformIO runs this post script after the framework has populated CPPPATH.
# Limit the workaround to IDE export; compilation uses the original paths.
if not env.IsIntegrationDump():
    Return()

Import("projenv")

framework_dir = env.PioPlatform().get_package_dir(
    "framework-arduinoespressif32-esp32-libs"
)
if not framework_dir:
    Return()

# Arduino-ESP32 3.3.12 lists these in flags/includes but does not ship the
# directories. Match full package paths so project/library mistakes stay visible.
# If a later package provides either directory, retain it automatically.
stale_paths = {
    os.path.normcase(os.path.normpath(os.path.join(framework_dir, "include", *suffix.split("/"))))
    for suffix in (
        "esp_system/port/soc",
        "espressif__esp_matter/connectedhomeip/connectedhomeip/src/platform/ESP32/bluedroid",
    )
}

for build_env in (env, projenv):
    includes = []
    for include in build_env.get("CPPPATH", []):
        resolved = os.path.normcase(os.path.normpath(
            build_env.Dir(build_env.subst(str(include))).get_abspath()
        ))
        if resolved not in stale_paths or os.path.isdir(resolved):
            includes.append(include)
    build_env.Replace(CPPPATH=includes)
