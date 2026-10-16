package il.fca.companion.ui

import il.fca.companion.net.*
import java.time.LocalDateTime

internal data class BookingFilterState(val applied: BookingFilters = BookingFilters(),
    val draft: BookingFilters = BookingFilters(), val open: Boolean = false, val invalid: Boolean = false,
    val vehicles: List<ManagedVehicle> = emptyList(), val members: List<FamilyMember> = emptyList(),
    val loading: Boolean = false, val loaded: Boolean = false, val error: Boolean = false)

internal enum class BookingOperation { CREATE, EDIT, CANCEL }

// Process-memory only. Never persisted/logged, and cleared on authenticated identity change.
internal data class BookingPending(val operation: BookingOperation, val ref: String?,
    val start: LocalDateTime, val end: LocalDateTime, val vehicleRef: String?,
    val original: BookingReservation?, val readQuery: BookingQuery? = null,
    val proposedRead: Boolean = false, val originalRead: Boolean = false) {
    private fun covers(query: BookingQuery, at: LocalDateTime, vehicle: String?): Boolean {
        val interval = query.effective ?: return false
        val filters = query.filters
        // Cover both old and proposed positions. A bounded read containing each start necessarily
        // overlaps each positive reservation interval, including reservations longer than the grid.
        return at >= interval.start && at < interval.end &&
            (filters.vehicleRef == null || filters.vehicleRef == vehicle) &&
            (filters.memberRef == null || (original != null && filters.memberRef == original.memberRef))
    }
    fun coveredBy(query: BookingQuery) = covers(query, start, vehicleRef) &&
        (original == null || covers(query, original.start, original.vehicleRef))
    fun observe(query: BookingQuery): BookingPending {
        val proposed = covers(query, start, vehicleRef)
        val old = original?.let { covers(query, it.start, it.vehicleRef) } ?: false
        if (!proposed && !old) return this
        return copy(readQuery = query, proposedRead = proposedRead || proposed, originalRead = originalRead || old)
    }
    val inspected get() = proposedRead && (original == null || originalRead)
}
