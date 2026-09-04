package uz.unnarsx.cherrygram.chats.ui

import android.view.View
import android.content.Context
import android.widget.LinearLayout
import org.telegram.messenger.MessageObject

class MessageMenuHelper {
    companion object {
        @JvmStatic
        fun getInstance(account: Int): MessageMenuHelper = MessageMenuHelper()
    }
    fun allowNewMessageMenu(): Boolean = false
    fun allowNewMessageMenu(msg: Any?): Boolean = false
    fun showDivider(): Boolean = false
    fun showDivider(a: Any?): Boolean = false
    fun showCustomDivider(a: Boolean = false): Boolean = false
    fun getMessageMenuAlpha(a: Boolean = false): Int = 255
    fun allowCompactStyle(): Boolean = false
    fun allowUnifiedScroll(a: Boolean = false): Boolean = false
    fun checkBlur(act: android.app.Activity?, a: Boolean, b: Boolean, f: Float) {}
    fun createMenu(a: Any, b: Any, c: Any, d: Any, e: Any, f: Any, g: Any) {}
    fun hideMessageView(a: Any, b: Any, c: Any, d: Any, e: Any, f: Boolean) {}

    class MaxHeightLinearLayout(context: Context) : LinearLayout(context) {
        fun setMaxWidth(w: Int) {}
        fun setMaxHeight(h: Int) {}
    }
}
