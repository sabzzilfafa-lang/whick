' 단일 서버 스크립트를 숨김 창으로 실행 (부모 프로세스 PATH 전달)
If WScript.Arguments.Count < 2 Then WScript.Quit 1

root = WScript.Arguments(0)
script = WScript.Arguments(1)
If Right(root, 1) <> "\" Then root = root & "\"

Set wsh = CreateObject("WScript.Shell")
pathEnv = wsh.Environment("PROCESS")("PATH")
cmd = "cmd /c ""set PATH=" & pathEnv & "&& """ & root & "scripts\" & script & """"""
wsh.Run cmd, 0, False
