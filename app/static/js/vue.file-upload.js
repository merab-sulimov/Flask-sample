/* globals FormData, Promise, Vue */
// define
Vue.component('file-upload', {
    template: '<div><label v-bind:for="name"><input type="file" v-bind:name="name" v-bind:id="id" v-bind:accept="accept" v-on:click="fileInputClick" v-on:change="fileInputChange" v-bind:multiple="multiple"><slot></slot></label><button type="button" v-on:click="fileUpload">{{ buttonText }}</button></div>',
    props: {
        class: String,
        name: {
            type: String,
            required: true
        },
        id: {
            type: String,
            required: true
        },
        action: {
            type: String,
            required: true
        },
        accept: String,
        multiple: String,
        headers: Object,
        method: String,
        buttonText: {
            type: String,
            default: 'Upload'
        }
    },
    data: function() {
        return {
            myFiles: [] // a container for the files in our field
        };
    },
    methods: {
        fileInputClick: function() {
            // click actually triggers after the file dialog opens
            this.$emit('onFileClick', this.myFiles);
        },
        fileInputChange: function() {
            // get the group of files assigned to this field
            var ident = this.id || this.name
            this.myFiles = document.getElementById(ident).files;
            this.$emit('onFileChange', this.myFiles);
        },
        _onProgress: function(e) {
            // this is an internal call in XHR to update the progress
            e.percent = (e.loaded / e.total) * 100;
            this.$emit('onFileProgress', e);
        },
        _handleUpload: function(file) {
            this.$emit('beforeFileUpload', file);
            var form = new FormData();
            var xhr = new XMLHttpRequest();
            try {
                form.append('Content-Type', file.type || 'application/octet-stream');
                // our request will have the file in the ['file'] key
                form.append('file', file);
            } catch (err) {
                this.$emit('onFileError', file, err);
                return;
            }

            return new Promise(function(resolve, reject) {

                xhr.upload.addEventListener('progress', this._onProgress, false);

                xhr.onreadystatechange = function() {
                    if (xhr.readyState < 4) {
                        return;
                    }
                    if (xhr.status < 400) {
                        var res = JSON.parse(xhr.responseText);
                        this.$emit('onFileUpload', file, res);
                        resolve(file);
                    } else {
                        var err = JSON.parse(xhr.responseText);
                        err.status = xhr.status;
                        err.statusText = xhr.statusText;
                        this.$emit('onFileError', file, err);
                        reject(err);
                    }
                }.bind(this);

                xhr.onerror = function() {
                    var err = JSON.parse(xhr.responseText);
                    err.status = xhr.status;
                    err.statusText = xhr.statusText;
                    this.$emit('onFileError', file, err);
                    reject(err);
                }.bind(this);

                xhr.open(this.method || "POST", this.action, true);
                if (this.headers) {
                    for(var header in this.headers) {
                        xhr.setRequestHeader(header, this.headers[header]);
                    }
                }
                xhr.send(form);
                this.$emit('afterFileUpload', file);
            }.bind(this));
        },
        fileUpload: function() {
            if(this.myFiles.length > 0) {
                // a hack to push all the Promises into a new array
                var arrayOfPromises = Array.prototype.slice.call(this.myFiles, 0).map(function(file) {
                    return this._handleUpload(file);
                }.bind(this));
                // wait for everything to finish
                Promise.all(arrayOfPromises).then(function(allFiles) {
                    this.$emit('onAllFilesUploaded', allFiles);
                }.bind(this)).catch(function(err) {
                    this.$emit('onFileError', this.myFiles, err);
                }.bind(this));
            } else {
                // someone tried to upload without adding files
                var err = new Error("No files to upload for this field");
                this.$emit('onFileError', this.myFiles, err);
            }
        }
    }
});
