package il.fca.companion.net

import java.time.Duration
import java.time.LocalDateTime

internal data class BookingFilters(val vehicleRef: String? = null, val memberRef: String? = null,
    val start: LocalDateTime? = null, val end: LocalDateTime? = null) {
    val valid get() = start == null || end == null || start < end
    fun matches(row: BookingReservation) = (vehicleRef == null || vehicleRef == row.vehicleRef) &&
        (memberRef == null || memberRef == row.memberRef) &&
        (start == null || row.end > start) && (end == null || row.start < end)
}

internal data class BookingInterval(val start: LocalDateTime, val end: LocalDateTime) {
    init { require(end > start && Duration.between(start, end) <= Duration.ofDays(42)) }
}

internal data class BookingQuery(val grid: BookingRange, val filters: BookingFilters = BookingFilters()) {
    init { require(filters.valid) }
    val effective: BookingInterval? get() {
        val start = maxOf(grid.start.atStartOfDay(), filters.start ?: grid.start.atStartOfDay())
        val end = minOf(grid.endExclusive.atStartOfDay(), filters.end ?: grid.endExclusive.atStartOfDay())
        return if (start < end) BookingInterval(start, end) else null
    }
}
