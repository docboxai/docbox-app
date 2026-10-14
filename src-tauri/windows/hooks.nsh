; Uninstall hooks for Tauri's NSIS template (bundle > windows > nsis > installerHooks).
; Inserted at the end of its uninstall section, so $INSTDIR, $UpdateMode and the confirm
; page's $DeleteAppDataCheckboxState are set. Tauri has already removed the files it
; installed, and the app data folder ($LOCALAPPDATA\<identifier>) when that box was ticked.

!macro NSIS_HOOK_POSTUNINSTALL
  ; Program files Tauri doesn't know about: bytecode that builds up to 0.1.1 wrote next to
  ; the bundled backend source (later ones write it under the data folder). Always removed:
  ; nothing the user keeps lives here.
  ${If} $INSTDIR != ""
    RMDir /r "$INSTDIR\backend"
    RMDir "$INSTDIR"
  ${EndIf}

  ; The user chose to delete DocBox's data (the box is unticked by default, and a silent
  ; uninstall or an update never deletes it): also the folder the `docbox` CLI and dev runs
  ; use when the app's own folder doesn't exist, platformdirs' user_data_dir("DocBox",
  ; "docbox"). Results saved in Documents\DocBox are the user's files and stay.
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    SetShellVarContext current
    RMDir /r "$LOCALAPPDATA\docbox\DocBox"
    RMDir "$LOCALAPPDATA\docbox"
  ${EndIf}
!macroend
