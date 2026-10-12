# Web Map Pariwisata Budaya Kota Yogyakarta

Website satu halaman untuk menampilkan lokasi wisata budaya dan menghitung
simulasi rute dari GPS pengguna atau titik yang dipilih pada peta. Frontend
HTML/CSS/JavaScript menggunakan Leaflet 1.9.4; Flask menyajikan halaman dan API.
Analisis Python memakai NetworkX, Shapely, dan pyproj. Tidak membutuhkan Node.js,
database, token API, atau proses build untuk menjalankan website.

## Menjalankan di komputer ini

Dependensi sudah dipasang di `.venv`. Buka PowerShell di folder proyek:

```powershell
.\.venv\Scripts\python.exe app.py
```

Buka **http://127.0.0.1:5000** pada browser. Hentikan server dengan `Ctrl+C`.
Jangan membuka `index.html` langsung karena peta memerlukan API server.

Untuk instalasi baru, gunakan Python 3.11 atau lebih baru. Interpreter yang
tersedia di komputer ini adalah `C:\Users\nino\anaconda3\python.exe`:

```powershell
& 'C:\Users\nino\anaconda3\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Jika Python sudah tersedia pada PATH, perintah pertama bisa menggunakan
`python -m venv .venv`. Versi dependensi dikunci di `requirements.txt`.

## Menggunakan peta

1. Pada tab **Wisata**, cari nama atau klik lokasi pada daftar/marker.
2. Pada tab **Simulasi Rute**, tekan **Gunakan lokasi saya** dan izinkan GPS.
   Alternatifnya, tekan **Pilih titik awal di peta** lalu klik pada peta.
3. Pilih skenario dan tekan **Hitung rute**. Rute, urutan kunjungan, jarak antar
   lokasi, dan total kilometer akan muncul.
4. Gunakan **Unduh GeoJSON** untuk menyimpan hasil perhitungan saat ini.
5. Kontrol layer mengatur wisata, jaringan jalan, dan rute. Tombol reset di
   bawah kontrol layer membersihkan rute/filter dan menampilkan seluruh wisata.
   Titik awal tetap tersedia untuk perhitungan berikutnya.

Pada layar kecil, tombol panel membuka/menutup sidebar. Pemilihan lokasi dan
keberhasilan perhitungan menutup panel agar peta terlihat. Peta dasar dan
library Leaflet memerlukan koneksi internet. Tidak dilakukan unduhan massal
atau penyimpanan tile OpenStreetMap untuk penggunaan offline.

GPS memerlukan izin browser dan konteks aman (HTTPS atau localhost). Jika
lokasi berada di luar jaringan Yogyakarta, perhitungan akan ditolak; gunakan
pilihan titik awal pada peta untuk mencoba simulasi. Ponsel yang membuka
alamat LAN komputer melalui HTTP biasanya tidak dapat memakai GPS. Untuk
pengujian sentuh melalui LAN, jalankan server pada semua antarmuka tanpa debug:

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app run --host 0.0.0.0
```

Buka `http://<IP-komputer>:5000` pada perangkat di jaringan yang sama; gunakan
titik awal manual. Penggunaan GPS pada perangkat lain memerlukan HTTPS.

## Struktur dan fungsi file

| File | Fungsi |
|---|---|
| `index.html` | Header, sidebar, peta, dan dialog tentang metode |
| `style.css` | Layout desktop, panel ponsel, simbol, dan kontrol sentuh |
| `app.js` | Pencarian, popup, GPS, pemilihan awal, pemanggilan API, unduhan |
| `app.py` | Server lokal, endpoint API, dan penanganan kesalahan |
| `network.py` | Validasi data, topologi, snapping, graf, Dijkstra, ekspor |
| `config.json` | Sumber data, CRS, nama atribut, toleransi, skenario |
| `requirements.txt` | Dependensi Python dengan versi tetap |
| `data/` | Data penelitian asli dan hasil ekspor opsional |
| `tests/test_app.py` | Uji jarak, topologi, dan API dengan unittest |
| `tests/browser.cjs` | Pengujian browser opsional dengan Playwright |

## Data yang digunakan

Data asli tetap tersimpan dengan nama:

- `data/JalanClip_49S_FeaturesToJSON.geojson`: 3.296 fitur jalan, CRS EPSG:32749.
- `data/Lokasi_Wisata_FeaturesToJSON.geojson`: enam titik wisata, CRS EPSG:32749.

Wisata menggunakan `OBJECTID` dan `Nama_Objek`. Atribut jalan yang dibaca adalah
`OBJECTID`, `NAMOBJ`, `REMARK`, dan `Shape_Length`. `Shape_Length` pada data ini
merupakan panjang meter; `SHAPE_Leng` berbeda dan tidak dipakai. `SRS_ID` pada
properties jalan juga tidak digunakan untuk menentukan CRS geometri.

Pada data saat ini seluruh nilai `ONEWAY` kosong. Analisis memakai graf tak
berarah dan seluruh kelas jalan, termasuk jalan setapak. Ini merupakan
simulasi jarak umum, tanpa informasi waktu, kemacetan, atau navigasi kendaraan.

### Mengganti data atau nama kolom

Ubah `roads_file`, `places_file`, `road_fields`, dan `place_fields` di konfigurasi,
kemudian mulai ulang server. Jalan harus berupa LineString/MultiLineString;
wisata berupa Point dengan ID unik serta nama yang tidak kosong.

CRS yang dinyatakan pada GeoJSON asli digunakan jika tersedia. Jika tidak ada,
`source_crs` pada konfigurasi menjadi acuan. Untuk GeoJSON baru dengan koordinat
longitude/latitude tanpa deklarasi CRS, atur `source_crs` menjadi `EPSG:4326`.
CRS pengukuran tetap `EPSG:32749`, sesuai wilayah Yogyakarta dan satuan meter.
Keluaran GeoJSON web menggunakan EPSG:4326 dengan urutan `[longitude, latitude]`.

Skema ringkas atribut yang bisa digunakan:

```json
{
  "jalan": {"OBJECTID": 1, "NAMOBJ": "Nama jalan jika tersedia", "REMARK": "Jalan Lokal", "Shape_Length": 120.5},
  "wisata": {"OBJECTID": 1, "Nama_Objek": "Nama wisata", "alamat": "", "kategori": "", "deskripsi": "", "foto": ""}
}
```

Atribut tambahan wisata bersifat opsional. Nilai kosong disembunyikan;
informasi yang belum tersedia tidak dibuat. Untuk foto lokal, simpan di
`data/photos/` dan isi atribut foto dengan `/data/photos/nama-foto.jpg`.
URL foto HTTPS juga didukung. Foto gagal dimuat akan disembunyikan.

## Konfigurasi skenario dan titik awal

`scenarios` berisi ID rute, nama, warna heksadesimal, dan urutan `place_ids`:

```json
{"id": "rute-1", "name": "Rute 1", "color": "#176b50", "place_ids": [4, 3, 1, 2]}
```

ID wisata pada data saat ini:

| ID | Nama |
|---|---|
| 1 | Keraton Yogyakarta |
| 2 | Situs Taman Sari |
| 3 | Museum Sonobudoyo |
| 4 | Benteng Vredeburg |
| 5 | Pura Pakualaman |
| 6 | Tugu Pal Putih |

Tiga skenario bawaan berlabel contoh simulasi. Titik awal diperoleh saat
pengguna memilih GPS/klik peta, bukan ditentukan oleh urutan skenario. Rute
berakhir di tujuan terakhir dan tidak otomatis kembali ke titik awal. Dijkstra
meminimalkan jarak antar pasangan berurutan; urutan wisata tidak dioptimalkan.

## Persiapan jaringan dan ekspor

Graf dibuat satu kali saat server mulai. Setiap permintaan memakai salinan
graf agar penyisipan titik awal/tujuan tidak mengubah jaringan bersama.

- Geometri kosong, tidak valid, koordinat tidak hingga, ruas nol, dan duplikasi
  identik dicatat. Ruas paralel dengan geometri berbeda dipertahankan.
- Garis dibagi pada vertex yang dipakai oleh ruas lain. Endpoint berdekatan
  disnap dengan batas `endpoint_snap_tolerance_m` (default 1 meter). Semua
  pemindahan endpoint masuk laporan untuk diperiksa.
- Persilangan tanpa vertex bersama tidak otomatis dihubungkan. Laporan
  mencatat titik persilangan tersebut untuk verifikasi simpang/beda elevasi.
  Simpang tambahan harus dikonfirmasi dan dinodekan pada data GIS.
- Setiap bobot dihitung dari geometri proyeksi dalam meter. Atribut panjang
  diperiksa; perbedaan lebih dari 1% atau 1 meter dicatat. Nilai atribut tidak
  menggantikan bobot hasil geometri setelah pemotongan/snapping.
- Lokasi disnap ke posisi terdekat sepanjang ruas, dengan batas
  `max_location_snap_m` (default 150 meter). Ruas dibagi pada posisi tersebut,
  termasuk ketika beberapa tujuan berada pada ruas yang sama.
- Jarak akses dari titik asli ke ruas tidak termasuk total. Lingkaran kecil
  pada rute menunjukkan posisi pada jaringan; titik asli tetap ditampilkan.

Perintah ini menghasilkan GeoJSON WGS84 serta laporan tanpa mengubah sumber:

```powershell
.\.venv\Scripts\python.exe network.py --prepare
```

Hasilnya: `data/wisata_budaya.geojson`, `data/jalan_yogyakarta.geojson`, dan
`data/network_report.json`. Laporan memuat ruas/node, komponen, fitur bermasalah,
pemindahan endpoint, perpotongan, dan jarak snapping wisata.

Contoh ekspor rute dari sekitar Tugu Pal Putih:

```powershell
.\.venv\Scripts\python.exe network.py --scenario rute-1 --lat -7.782911 --lon 110.367
```

Hasil tersimpan sebagai `data/rute_wisata.geojson`. Gunakan `--config` dan
`--output-dir` untuk lokasi konfigurasi/keluaran lain. Website menghitung
hasil saat diminta melalui API; hasil GPS tidak otomatis disimpan di server.

GeoJSON rute berupa FeatureCollection dengan satu LineString. Properties:
`route_id`, `route_name`, `color`, `is_example`, `total_distance_m`,
`total_distance_km`, `start`, `visits`, `legs`, `snapping`, `method`, dan `note`.
`legs` memuat asal, tujuan, ID tujuan, jarak meter, dan ID ruas sumber.

## API

| Endpoint | Hasil |
|---|---|
| `GET /api/wisata` | GeoJSON titik wisata di WGS84 |
| `GET /api/jalan` | GeoJSON ruas jaringan di WGS84 |
| `GET /api/skenario` | Daftar urutan wisata dan batas snapping |
| `POST /api/rute` | GeoJSON hasil Dijkstra |

Contoh permintaan dari PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5000/api/rute' -ContentType 'application/json' -Body '{"scenario_id":"rute-1","start":{"lat":-7.782911,"lon":110.367}}'
```

Input tidak valid menghasilkan HTTP 400. Titik terlalu jauh atau jaringan
tidak terhubung menghasilkan HTTP 422 tanpa geometri rute. Data sumber yang
tidak dapat digunakan menghasilkan HTTP 503; halaman tetap dapat dibuka.
Kesalahan memakai bentuk `{"error":{"code":"…","message":"…"}}`.

## Pengujian

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Pengujian mencakup jarak yang diketahui, ruas paralel, arah geometri, vertex
bersama, endpoint bergeser, persilangan tidak terhubung, MultiLineString,
duplikasi, data kosong, beberapa titik pada ruas yang sama, jarak akses,
rute nol, ketiga skenario pada data asli, serta validasi/status API.

Pengujian browser opsional memakai Node.js dan Edge/Chrome terpasang:

```powershell
npm.cmd install --prefix .qa --no-save --package-lock=false playwright
# Jalankan server terlebih dahulu pada terminal lain.
node tests/browser.cjs
```

Browser QA memeriksa pencarian, popup, titik awal manual, GPS yang disimulasikan,
ketiga rute, jarak/urutan, unduhan, layer, reset, dialog, kegagalan GPS,
lokasi di luar cakupan, dan viewport desktop/ponsel. Screenshot ada di `.qa/`.
Verifikasi implementasi: 22 pengujian Python/API lulus; pengujian browser Edge
pada viewport desktop dan ponsel lulus tanpa exception JavaScript, termasuk
pergantian skenario saat permintaan berjalan dan titik manual setelah GPS
berada di luar Yogyakarta.
GPS fisik, keyboard layar, safe area, dan pengalaman sentuh tetap perlu dicoba
pada ponsel nyata; emulasi browser tidak menggantikan pengujian perangkat.

## Keterbatasan dan kesalahan umum

- Titik wisata belum tentu merupakan pintu masuk. Snapping terdekat belum
  membuktikan akses fisik dari lokasi ke ruas; verifikasi diperlukan untuk
  hasil penelitian final. Data Benteng Vredeburg berjarak sekitar 104 meter
  dari ruas terdekat sehingga batas 150 meter dipakai sebagai default.
- Jaringan memiliki komponen terpisah. Sistem menolak perjalanan yang tidak
  terhubung dan tidak membuat garis lurus sebagai pengganti.
- Tidak ada aturan satu arah, larangan belok, elevasi, atau batas akses moda.
  Endpoint snapping merupakan asumsi persiapan yang perlu diperiksa di GIS.
- Mengubah data/konfigurasi memerlukan restart server karena graf disimpan
  dalam memori selama proses berjalan.
- Jika muncul `ModuleNotFoundError`, jalankan Python dari `.venv` dan instal
  dependensi. Jika pip melaporkan tidak ada paket dan `PIP_NO_INDEX=1`,
  periksa konfigurasi pip/akses index paket pada lingkungan pengembangan.
- Jika port 5000 terpakai, gunakan `python -m flask --app app:create_app run --port 5001`
  melalui interpreter `.venv`, lalu buka alamat dengan port tersebut.
- Jika peta dasar/library gagal dimuat, periksa internet. Marker/rute dapat
  tetap digunakan saat hanya tile basemap yang gagal.

Referensi: [Leaflet 1.9.4](https://leafletjs.com/reference-1.9.4.html),
[NetworkX Dijkstra](https://networkx.org/documentation/stable/reference/algorithms/shortest_paths.html),
[Shapely](https://shapely.readthedocs.io/), [pyproj](https://pyproj4.github.io/pyproj/),
[Geolocation](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation/getCurrentPosition),
dan [kebijakan tile OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/).
