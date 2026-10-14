; SPDX-License-Identifier: Apache-2.0
; TotemOps TEST-ONLY NSIS QA package. No Minecraft/JAR/credentials included.
Unicode True
RequestExecutionLevel user
SetCompressor /SOLID lzma
Name "TotemOps QA Installer - TEST ONLY"
OutFile "TotemOps-QA-Setup.exe"
InstallDir "$LOCALAPPDATA\TotemOps-QA-Install-20261014"
ShowInstDetails show
ShowUninstDetails show
Page directory
Page instfiles
UninstPage instfiles

Section "Offline QA Installer"
    SetOutPath "$INSTDIR"
    File "Launch-Test.cmd"
    File "README-QA.txt"
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    CreateShortCut "$DESKTOP\TotemOps-QA-Test.lnk" "$INSTDIR\Launch-Test.cmd"
SectionEnd

Section "Uninstall"
    Delete "$DESKTOP\TotemOps-QA-Test.lnk"
    Delete "$INSTDIR\Launch-Test.cmd"
    Delete "$INSTDIR\README-QA.txt"
    Delete "$INSTDIR\fail.flag"
    Delete "$INSTDIR\outcome.txt"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir "$INSTDIR"
SectionEnd
