package online.cosger.jarvis.net

import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** ADR-077: the messages for operating an app on the phone and approving a run. */
class PhoneProtocolTest {
    @Test
    fun anInstructionForTheAccessibilityServiceIsParsed() {
        val e = Protocol.parse("""{"type":"phone_op","req":"ab12","op":"tap","index":4}""") as ServerEvent.PhoneOp
        assertEquals("ab12", e.req)
        assertEquals("tap", e.op)
        assertEquals("4", e.args["index"]?.jsonPrimitive?.content)
    }

    @Test
    fun anApprovalAskAndItsSettlementAreParsed() {
        val ask = Protocol.parse("""{"type":"phone_approval","id":7,"app":"gojek","label":"Gojek","goal":"Pesan GoRide ke kantor",
            "requested_by":"device:HP","status":"awaiting","expires_in_s":840}""") as ServerEvent.PhoneApproval
        assertEquals(7L, ask.id)
        assertEquals("awaiting", ask.status)
        assertEquals("Gojek", ask.label)
        assertEquals(840L, ask.expiresInS)
        val done = Protocol.parse("""{"type":"phone_approval","id":7,"status":"approved","task_id":12}""") as ServerEvent.PhoneApproval
        assertEquals("approved", done.status)
        assertNull(Protocol.parse("""{"type":"phone_approval","status":"awaiting"}"""))   // no id: ignored
    }

    @Test
    fun thePhoneSaysItCanOperateApps() {
        assertTrue(JarvisSocket.CAPS.split(",").contains("phone_agent"))
    }
}
