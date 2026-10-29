package il.fca.companion.push

import org.junit.Assert.*
import org.junit.Test

class ProductionPushIdentityTest {
    @Test fun onlyApprovedProductionIdentityIsAccepted() {
        val packageName = "il.fca.companion"
        val project = "family-car-agent-dev"
        val sender = "452367109329"
        val app = "1:452367109329:android:c5a668180a0a8b84bdc9f0"
        assertTrue(PushPlatform.enabled)
        assertTrue(PushPlatform.validIdentity(packageName, project, sender, app))
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
