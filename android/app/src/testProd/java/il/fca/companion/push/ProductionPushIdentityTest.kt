package il.fca.companion.push

import org.junit.Assert.*
import org.junit.Test

class ProductionPushIdentityTest {
    @Test fun onlyApprovedProductionIdentityIsAccepted() {
        val packageName = "com.familycaragent.app"
        val project = "family-car-agent"
        val sender = "249909620080"
        val app = "1:249909620080:android:c0f07c3b74400bfaee33b5"
        assertTrue(PushPlatform.enabled)
        assertTrue(PushPlatform.validIdentity(packageName, project, sender, app))
        assertFalse(PushPlatform.validIdentity("il.fca.companion", "family-car-agent-dev",
            "452367109329", "1:452367109329:android:c5a668180a0a8b84bdc9f0"))
        assertFalse(PushPlatform.validIdentity("il.fca.companion.dev", project, sender, app))
        assertFalse(PushPlatform.validIdentity(packageName, project, sender,
            "1:452367109329:android:f84f77ce1bb4784cbdc9f0"))
        for (value in listOf(null, "", "wrong")) {
            assertFalse(PushPlatform.validIdentity(packageName, value, sender, app))
            assertFalse(PushPlatform.validIdentity(packageName, project, value, app))
            assertFalse(PushPlatform.validIdentity(packageName, project, sender, value))
        }
    }
}
