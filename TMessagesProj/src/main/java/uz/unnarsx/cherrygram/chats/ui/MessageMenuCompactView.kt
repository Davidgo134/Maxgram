package uz.unnarsx.cherrygram.chats.ui

import android.content.Context
import android.view.View
import org.telegram.messenger.MessageObject

class MessageMenuCompactView : View {
    constructor(context: Context) : super(context)
    constructor(
        a: Any?, b: MessageObject?, c: Int, d: Boolean, e: Boolean, f: Boolean, g: Boolean, h: Boolean, i: Boolean, j: Boolean
    ) : super(if (a is Context) a else null)

    companion object {
        @JvmStatic
        fun allowCompactStyle(): Boolean = false
    }
}
