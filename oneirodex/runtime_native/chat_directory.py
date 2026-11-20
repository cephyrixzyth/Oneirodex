"""Read-only projections for the member-visible chat directory."""


class ChatDirectory:
    def channels(self, user):
        from oneirodex.utils.chat import list_channels_for_user

        return list_channels_for_user(user)

    def spaces(self, user):
        from oneirodex.utils.chat_spaces import channels_for_space, spaces_for_user
        from oneirodex.utils.livekit_rtc import voice_room_name

        payload = []
        for space in spaces_for_user(user):
            channels = channels_for_space(user, space)
            rows = []
            for channel in channels:
                row = channel.to_dict()
                if channel.kind == 'voice':
                    row['room'] = voice_room_name(channel.id)
                rows.append(row)
            payload.append({
                **space.to_dict(),
                'channels': [row for row in rows if row.get('kind') == 'channel'],
                'voice_channels': [row for row in rows if row.get('kind') == 'voice'],
            })
        return payload
