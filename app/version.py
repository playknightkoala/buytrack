"""應用程式版本（單一來源）。

改版流程：
1. 修改此處的 __version__（SemVer：MAJOR.MINOR.PATCH）。
2. 在專案根目錄 CHANGELOG.md 新增該版本的改版說明區段。
3. commit + push，並打 git tag：git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z
4. 重建 bot（docker compose up -d --build bot）。
   bot 啟動時若偵測到此版本尚未公告過，會自動把 CHANGELOG 對應段落
   推播給「已開通使用者」，並在 DB 記錄避免重複公告。
"""

__version__ = "1.3.0"
