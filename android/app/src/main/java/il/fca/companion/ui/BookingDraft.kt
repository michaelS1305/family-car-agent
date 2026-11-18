package il.fca.companion.ui

import il.fca.companion.net.*
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime

internal enum class BookingSelection { NONE, EDIT, CANCEL }
internal data class BookingDraft(val original: BookingReservation? = null,
    val startDate: LocalDate, val endDate: LocalDate, val startTime: LocalTime? = null,
    val endTime: LocalTime? = null, val vehicleRef: String? = original?.vehicleRef) {
    val start get() = startTime?.let { startDate.atTime(it) }
    val end get() = endTime?.let { endDate.atTime(it) }
    fun change() = BookingChange(checkNotNull(start), checkNotNull(end), vehicleRef,
        if (original == null) vehicleRef != null else vehicleRef != original.vehicleRef)
}
internal data class BookingAction(val selection: BookingSelection = BookingSelection.NONE,
    val draft: BookingDraft? = null, val confirmation: BookingReservation? = null,
    val vehicles: List<ManagedVehicle> = emptyList(), val vehiclesLoaded: Boolean = false,
    val vehiclesLoading: Boolean = false, val vehicleError: Boolean = false,
    val submitting: Boolean = false, val error: String? = null, val uncertain: Boolean = false,
    val reconciling: Boolean = false, val notice: String? = null)

internal fun bookingEligible(row: BookingReservation, now: LocalDateTime) = row.isMine && row.end > now

internal fun bookingRejection(code: String?) = when (code) {
    "RESERVATION_CONFLICT" -> "קיימת הזמנה חופפת לרכב או לטווח שנבחר."
    "VEHICLE_REQUIRED" -> "יש לבחור רכב להזמנה."
    "VEHICLE_NOT_FOUND_OR_UNAVAILABLE" -> "הרכב אינו זמין. יש לבחור רכב פעיל."
    "RESERVATION_NOT_FOUND_OR_UNAVAILABLE", "RESERVATION_AMBIGUOUS" -> "ההזמנה כבר אינה זמינה לעריכה או לביטול."
    "INVALID_RESERVATION_TIME" -> "יש לבדוק את שעות ההתחלה והסיום."
    "RESERVATION_TIME_IN_PAST" -> "לא ניתן לשנות את ההזמנה לזמן שכבר עבר."
    else -> "לא ניתן להשלים את הפעולה כרגע."
}
