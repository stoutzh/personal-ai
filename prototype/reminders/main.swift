import Foundation
import EventKit

func emit(_ value: [String: Any], _ code: Int32 = 0) -> Never {
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([10]))
    }
    exit(code)
}
func fail(_ code: String) -> Never { emit(["ok": false, "error_code": code], 1) }
let args = Array(CommandLine.arguments.dropFirst())
guard let command = args.first, ["status", "authorize", "lists", "read", "create"].contains(command) else { fail("invalid_request") }
guard (command == "read" && args.count == 3) || (command != "read" && args.count == 1) else { fail("invalid_request") }
let authorization = EKEventStore.authorizationStatus(for: .reminder)
func statusName(_ status: EKAuthorizationStatus) -> String {
    switch status {
    case .notDetermined: return "not_determined"
    case .restricted: return "restricted"
    case .denied: return "denied"
    case .fullAccess: return "authorized"
    default: return "unsupported"
    }
}
if command == "status" { emit(["ok": true, "authorization": statusName(authorization)]) }
let store = EKEventStore()
// Timeout exits without exposing EventKit errors or personal data.
DispatchQueue.main.asyncAfter(deadline: .now() + (command == "authorize" ? 55 : 15)) { fail("timeout") }
if command == "authorize" {
    store.requestFullAccessToReminders { granted, _ in
        emit(["ok": granted, "authorization": statusName(EKEventStore.authorizationStatus(for: .reminder))], granted ? 0 : 1)
    }
} else {
    guard authorization == .fullAccess else { fail("permission_required") }
    if command == "lists" {
        let lists = store.calendars(for: .reminder).map { ["id": $0.calendarIdentifier, "title": String($0.title.prefix(256))] }
        emit(["ok": true, "lists": Array(lists.prefix(100)), "truncated": lists.count > 100])
    }
    if command == "create" {
        let input = FileHandle.standardInput.readData(ofLength: 8193)
        guard input.count <= 8192,
              let payload = (try? JSONSerialization.jsonObject(with: input)) as? [String: Any],
              let listID = payload["list_id"] as? String,
              let title = payload["title"] as? String, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, title.count <= 200,
              let operation = payload["operation_id"] as? String,
              operation.range(of: "^[0-9a-f]{32}$", options: .regularExpression) != nil,
              let source = payload["source"] as? String, source.count <= 300,
              let due = payload["due"] as? [String: Any] else { fail("invalid_request") }
        guard let target = store.calendar(withIdentifier: listID), target.allowedEntityTypes.contains(.reminder) else { fail("list_not_found") }
        guard target.allowsContentModifications else { fail("read_only_list") }
        var components: DateComponents? = nil
        if !due.isEmpty {
            guard let year = due["year"] as? Int, let month = due["month"] as? Int, let day = due["day"] as? Int else { fail("invalid_due") }
            var value = DateComponents(year: year, month: month, day: day)
            var calendar = Calendar(identifier: .gregorian)
            if let hour = due["hour"] as? Int {
                guard let minute = due["minute"] as? Int,
                      let name = due["timezone"] as? String, let zone = TimeZone(identifier: name),
                      (0...23).contains(hour), (0...59).contains(minute) else { fail("invalid_due") }
                calendar.timeZone = zone
                value.timeZone = zone; value.hour = hour; value.minute = minute
            } else if due["minute"] != nil || due["timezone"] != nil { fail("invalid_due") }
            value.calendar = calendar
            guard value.isValidDate(in: calendar) else { fail("invalid_due") }
            components = value
        }
        let marker = "Aion operation: " + operation
        let predicate = store.predicateForReminders(in: [target])
        store.fetchReminders(matching: predicate) { existing in
            guard let existing = existing else { fail("fetch_failed") }
            if let prior = existing.first(where: { ($0.notes ?? "").components(separatedBy: "\n").contains(marker) }) {
                emit(["ok": true, "id": prior.calendarItemIdentifier, "created": false])
            }
            let reminder = EKReminder(eventStore: store)
            reminder.calendar = target; reminder.title = title
            reminder.dueDateComponents = components
            if let components = components, components.hour != nil, let alarmDate = components.date {
                reminder.addAlarm(EKAlarm(absoluteDate: alarmDate))
            }
            reminder.notes = marker + (source.isEmpty ? "" : "\nSource: " + source)
            do {
                try store.save(reminder, commit: true)
                emit(["ok": true, "id": reminder.calendarItemIdentifier, "created": true])
            } catch { fail("save_failed") }
        }
        RunLoop.main.run()
        exit(1)
    }
    guard let limit = Int(args[2]), (1...20).contains(limit) else { fail("invalid_limit") }
    guard let calendar = store.calendar(withIdentifier: args[1]), calendar.allowedEntityTypes.contains(.reminder) else { fail("list_not_found") }
    let predicate = store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: [calendar])
    store.fetchReminders(matching: predicate) { fetched in
        guard let fetched = fetched else { fail("fetch_failed") }
        let items = fetched.filter { !$0.isCompleted && $0.calendar.calendarIdentifier == args[1] }.sorted {
            let left = $0.dueDateComponents?.date ?? .distantFuture
            let right = $1.dueDateComponents?.date ?? .distantFuture
            return left == right ? $0.calendarItemIdentifier < $1.calendarItemIdentifier : left < right
        }
        let rows: [[String: Any]] = items.prefix(limit).map { reminder in
            var due: [String: Int] = [:]
            if let d = reminder.dueDateComponents {
                due["year"] = d.year; due["month"] = d.month; due["day"] = d.day
                due["hour"] = d.hour; due["minute"] = d.minute
            }
            return ["id": reminder.calendarItemIdentifier, "title": String((reminder.title ?? "").prefix(512)), "due": due, "completed": false]
        }
        emit(["ok": true, "list_id": args[1], "items": rows, "truncated": items.count > limit])
    }
}
RunLoop.main.run()
