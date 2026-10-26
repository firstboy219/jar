package online.cosger.jarvis.ui.console

import org.junit.Assert.assertEquals
import org.junit.Test

class NotesScreenTest {
    @Test fun `the notes page gets the token in the fragment, like the desk`() {
        assertEquals("https://vis1.cosger.online/notes/#t=abc%2B1%2F2&app=1", notesUrl(" https://vis1.cosger.online/ ", "abc+1/2"))
    }
}
