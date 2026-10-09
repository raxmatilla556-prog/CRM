' Telegram bot va avtomatik vazifalarni (kunlik hisobot, qarz eslatmasi, zaxira) yashirin ishga tushiradi.
' Loglar: logs\bot.log
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = root
sh.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
sh.Environment("PROCESS")("PYTHONUNBUFFERED") = "1"
sh.Run "cmd /c """ & root & "\.venv\Scripts\python.exe"" manage.py telegram_bot >> logs\bot.log 2>&1", 0, False
