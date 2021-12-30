## 理念
* フローの可視化
* 機能ごとの部品化
* 並列処理

## 構想
* メッセージ方式IF
	* MessageIFが各クラス間のやりとりを集約する
	* 従来のスター方式では、クラスを追加すると各クラスにIFを追加する必要があったが、メッセージ方式ではMessageIFに追加するだけでよい
	* MessageIFに管理するスレッド分だけのキューを持たせることで、マルチスレッド、マルチCPU環境でもアクセス競合を起こさなくできる
	* EnQueue、DeQueueは競合しないように設計する
		* EnQueueではhead、DeQueueではtailだけを操作
		* EnQueue前にIsFull、DeQueue前にIsEmptyをチェックすることで、head、tailが干渉しないようにする
		* EnQueue-DeQueueは競合しないが、EnQueue-EnQueueでは競合してしまうので、EnQueueするのは単一のスレッドに制限する
		* DeQueueも同様に単一のスレッドに限定する

* Errorクラス
	* システムエラー、アプリケーションエラーを管理するクラス
	* SetErrorとResetErrorを提供する
	* 異常状態を各クラスへ通知する機能とリセット機能を一元管理する
	* 異常一覧はjson/xml形式でファイル保管し別プログラム（画面など）からも読めるようにする
	* 正の異常コードは固定メッセージ、負の異常コードは動的なメッセージを持つ(エラー文字列を転送できない環境ではエラーコードだけ表示する）
* Clockクラス
	* システム内で単一の時刻を提供する
* Logクラス
	* WriteLogを提供する

* デバッグモード
	* テーブル実行、メッセージ送受信をDebugLogに出力する
	* 各クラスごとにON/OFFできる
	* DebugLogはLogを継承して全く同一の機能を持つが、別クラスとする（Logクラスのデバッグモードを実行するときに循環呼出になることを避けるため）

* 同期／非同期呼び出し機能の整理
	* Request(キューの末尾に挿入), Interrupt(現在の実行状況をキューの先頭に退避、次のステップに挿入)
	* Interruptされたくない処理は1ステップ内で実行しきる
	* MessageIFにGetIntercepterメッセージを送ることでInterruptQueueへのポインタを受け取る
		* 通常Requestは呼出元からMessageIFへの送信、MessageIFから呼出先への送信を経て実行されるため遅い
		* 素早くInterruptを処理するために、直接呼出先のQueueに挿入できるようにする
		* InterruptQueueは複数のスレッドからEnQueueされる可能性があるため、MutexLockを設ける
	* Requestの完了はHdlに持たせたFinTblFlagを確認する
	* HdlのVerifyは型レベルで行う

* MainTbl
	* 最後のステップで自分のクラスへMainTblを実行するRequestを送信する
	* このときHdlを流用することで変数を保持する
		* 明示的にループすることと変数を保持することを記述する

* 定型クラス
	* 要求に応じてMainTblで処理を実行するDriverクラス
	* 状態遷移を行い、状態毎に処理が変わるStateクラス
	* 条件が成立した時だけ処理を実行するEventクラス
	* シーケンスを管理するScenarioクラス
	* Template必要？サンプルコードで充分？
