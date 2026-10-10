/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 *
 *  BlueZ - Bluetooth protocol stack for Linux
 *
 *  Copyright (C) 2006-2007  Nokia Corporation
 *  Copyright (C) 2004-2009  Marcel Holtmann <marcel@holtmann.org>
 *
 *
 */

struct media_endpoint;
struct local_player;

typedef void (*media_endpoint_cb_t) (struct media_endpoint *endpoint,
					void *ret, int size, void *user_data);

int media_register(struct btd_adapter *btd_adapter);
void media_unregister(struct btd_adapter *btd_adapter);

#ifdef HAVE_A2DP
struct a2dp_sep *media_endpoint_get_sep(struct media_endpoint *endpoint);
#else
struct a2dp_sep;
static inline struct a2dp_sep *media_endpoint_get_sep(
						struct media_endpoint *endpoint)
{
	return NULL;
}
#endif

const char *media_endpoint_get_uuid(struct media_endpoint *endpoint);
bool media_endpoint_get_delay_reporting(struct media_endpoint *endpoint);
uint8_t media_endpoint_get_codec(struct media_endpoint *endpoint);
struct btd_adapter *media_endpoint_get_btd_adapter(
					struct media_endpoint *endpoint);
bool media_endpoint_is_broadcast(struct media_endpoint *endpoint);

const struct media_endpoint *media_endpoint_get_asha(void);

/*
 * Local media player
 */
struct local_player_callback {
	void (*status_changed)(void *user_data);
	void (*track_position)(uint32_t old_ms, uint32_t new_ms,
							void *user_data);
	void (*track_changed)(void *user_data);
	void (*settings_changed)(const char *key, void *user_data);
	/* The items of the player's Playlist (now playing) folder changed */
	void (*now_playing_changed)(void *user_data);

	/* Player removed (no further callbacks) */
	void (*player_removed)(void *user_data);
};

unsigned int local_player_register_callbacks(struct local_player *lp,
		const struct local_player_callback *cb, void *user_data);
void local_player_unregister_callbacks(struct local_player *lp,
							unsigned int id);

struct btd_adapter *local_player_get_adapter(struct local_player *lp);

GList *local_player_list_settings(struct local_player *lp);
const char *local_player_get_setting(struct local_player *lp, const char *key);
int local_player_set_setting(struct local_player *lp, const char *key,
							const char *value);
const char *local_player_get_metadata(struct local_player *lp, const char *key);
GList *local_player_list_metadata(struct local_player *lp);
const char *local_player_get_status(struct local_player *lp);
uint32_t local_player_get_position(struct local_player *lp);
uint32_t local_player_get_duration(struct local_player *lp);
const char *local_player_get_player_name(struct local_player *lp);
bool local_player_have_track(struct local_player *lp);
bool local_player_play(struct local_player *lp);
bool local_player_stop(struct local_player *lp);
bool local_player_pause(struct local_player *lp);
bool local_player_seek(struct local_player *lp, int64_t offset_usec);
bool local_player_next(struct local_player *lp);
bool local_player_previous(struct local_player *lp);

/*
 * Browsing a local player (target role): the player object implements
 * org.bluez.MediaFolder1, its items org.bluez.MediaItem1. The root of its
 * media library is the player object itself; the now playing list is the
 * folder object in its Playlist property. The player has one current folder,
 * shared by everyone browsing it, so each request below first moves it to the
 * folder the request is about, and requests are run one at a time.
 *
 * The callbacks are called exactly once, also when the player goes away
 * before the answer (err -ECANCELED). err is a negative errno: -ENOTSUP when
 * the player does not support the request, -ENOENT for an object it does not
 * know.
 */
struct local_player_item {
	char *path;
	char *name;
	char *type;		/* "audio", "video" or "folder" */
	char *folder_type;	/* folders: "mixed", "titles", "albums", ... */
	bool playable;
	/* "Title", "Artist", "Album", "Genre", "TrackNumber",
	 * "NumberOfTracks", "Duration" (ms) as strings, the keys of the track
	 */
	GHashTable *metadata;
};

void local_player_item_free(void *data);

typedef void (*local_player_folder_cb)(int err, uint32_t num_items,
							void *user_data);
/* items: a list of struct local_player_item, the callee's to free */
typedef void (*local_player_items_cb)(int err, GSList *items,
							void *user_data);
typedef void (*local_player_search_cb)(int err, const char *folder,
					uint32_t num_items, void *user_data);

const char *local_player_get_path(struct local_player *lp);
bool local_player_browsable(struct local_player *lp);
bool local_player_searchable(struct local_player *lp);
const char *local_player_get_playlist(struct local_player *lp);
/* The current track's object, from its metadata's mpris:trackid (NULL if none) */
const char *local_player_get_track(struct local_player *lp);

int local_player_change_folder(struct local_player *lp, const char *folder,
				local_player_folder_cb cb, void *user_data);
int local_player_list_items(struct local_player *lp, const char *folder,
				uint32_t start, uint32_t end,
				local_player_items_cb cb, void *user_data);
int local_player_search(struct local_player *lp, const char *value,
				local_player_search_cb cb, void *user_data);
int local_player_play_item(struct local_player *lp, const char *item);
int local_player_add_to_now_playing(struct local_player *lp,
							const char *item);

typedef void (*local_player_added_t)(struct local_player *lp, void *user_data);

unsigned int local_player_register_watch(local_player_added_t cb,
							void *user_data);
void local_player_unregister_watch(unsigned int id);

gboolean hfp_hf_set_configuration(struct media_endpoint *endpoint,
					const char *ep_path,
					media_endpoint_cb_t cb,
					void *user_data,
					GDestroyNotify destroy);
